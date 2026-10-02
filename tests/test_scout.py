"""MDN Scout (ADR-0002): training, missing-Anchor path, 95 % bounding box,
end-to-end on the default simulator (#27)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from gateway.scout import Mixture, MdnScout, ScoutConfig, bbox, run_scout  # noqa: E402
from gateway.sim import load_layout, simulate_session  # noqa: E402

DEFAULT_LAYOUT = Path(__file__).resolve().parents[1] / "layouts" / "techhub_default.yaml"
ANCHORS = ["A1", "A2", "A3", "A4"]
ROOM = (4.0, 3.0)
ANCHOR_XY = {"A1": (0.0, 0.0), "A2": (4.0, 0.0), "A3": (4.0, 3.0), "A4": (0.0, 3.0)}


def _rssi_at(x, y):
    """Noise-free log-distance RSSI from each toy Anchor."""
    return {
        a: -40.0 - 27.0 * np.log10(max(np.hypot(x - ax, y - ay), 0.1))
        for a, (ax, ay) in ANCHOR_XY.items()
    }


def _toy_set():
    xy = [(x, y) for x in (0.5, 1.5, 2.5, 3.5) for y in (0.5, 1.5, 2.5)]
    return [_rssi_at(x, y) for x, y in xy], np.array(xy)


def test_loss_decreases_on_a_toy_set():
    rssi, xy = _toy_set()
    scout = MdnScout(ANCHORS, room=ROOM, config=ScoutConfig(epochs=200, seed=0))
    losses = scout.fit(rssi, xy)
    assert len(losses) == 200
    assert losses[-1] < losses[0] - 1.0


def _window(rssi, sufficient=True):
    return {
        "sufficient": sufficient,
        "anchors": {a: None if r is None else {"rssi": r, "dcfr": None}
                    for a, r in rssi.items()},
    }


def test_window_with_a_missing_anchor_gives_a_valid_mixture_and_estimate():
    rssi, xy = _toy_set()
    scout = MdnScout(ANCHORS, room=ROOM, config=ScoutConfig(epochs=100, seed=0))
    scout.fit(rssi, xy)
    window = _window(dict(_rssi_at(1.5, 1.5), A4=None))

    mixture = scout.predict(window)
    assert mixture.weights.shape == (3,)
    assert mixture.weights.sum() == pytest.approx(1.0)
    assert np.all(mixture.sds > 0) and np.all(np.isfinite(mixture.means))
    x, y = scout.estimate(window)
    assert 0 <= x <= ROOM[0] and 0 <= y <= ROOM[1]
    assert scout.estimate(_window(_rssi_at(1.5, 1.5), sufficient=False)) is None


def _random_mixture(rng, room):
    w = rng.dirichlet(np.ones(3) * 0.5)
    means = rng.uniform((0, 0), room, size=(3, 2))
    sds = np.exp(rng.uniform(np.log(0.05), np.log(5.0), size=(3, 2)))
    return Mixture(weights=w, means=means, sds=sds)


def test_bbox_contains_the_mixture_mean_and_stays_inside_the_room():
    rng = np.random.default_rng(0)
    room = (8.0, 6.0)
    # A light, broad, far kernel: its 4 % of samples are the least dense,
    # so none is in the densest 95 %, yet it drags the mean to (1.24, 1.16),
    # outside the main kernel's ~1 +/- 0.15 m box.
    light_far = Mixture(weights=np.array([0.96, 0.04, 0.0]),
                        means=np.array([[1.0, 1.0], [7.0, 5.0], [4.0, 3.0]]),
                        sds=np.array([[0.05, 0.05], [0.5, 0.5], [0.05, 0.05]]))
    for mixture in [light_far] + [_random_mixture(rng, room) for _ in range(200)]:
        x0, y0, x1, y1 = bbox(mixture, room)
        mx, my = mixture.mean()
        assert x0 <= mx <= x1 and y0 <= my <= y1
        assert 0 <= x0 <= x1 <= room[0] and 0 <= y0 <= y1 <= room[1]


def test_bbox_of_one_gaussian_is_its_95_percent_disc():
    """The densest 95 % of an isotropic Gaussian is the disc of radius
    sigma * sqrt(-2 ln 0.05) (chi-square, 2 dof), so the box is its square."""
    sigma = 0.5
    mixture = Mixture(weights=np.array([1.0, 0.0, 0.0]),
                      means=np.array([[4.0, 3.0]] * 3),
                      sds=np.full((3, 2), sigma))
    x0, y0, x1, y1 = bbox(mixture, (8.0, 6.0))
    r = sigma * np.sqrt(-2 * np.log(0.05))
    assert (x0, y0, x1, y1) == pytest.approx((4 - r, 3 - r, 4 + r, 3 + r), abs=0.1 * r)


def test_run_scout_on_the_default_simulator(tmp_path):
    """#27 acceptance: bbox hit-rate >= 90 % and mean bbox area well below
    the room, reported next to the k-NN baseline; weights and training
    config saved with the Radio map. "Well below" is fixed at < 60 % of the
    room: the box measures ~50 % on the default layout, set by its 3 dB
    shadowing, and shrinking it further cost hit-rate (~80 % at 44 %)."""
    layout = load_layout(DEFAULT_LAYOUT)
    sim = tmp_path / "sim"
    t = 1_000_000.0
    simulate_session(layout, sim, "calibration", dwell_s=5.0, seed=1, t_start=t)
    simulate_session(layout, sim, "test", dwell_s=10.0, seed=2, t_start=t + 10_000.0)

    result = run_scout(sim, layout, tmp_path / "eval")

    scout = result["scout"]["overall"]
    assert scout["availability"] > 0.9
    assert scout["bbox_hit_rate"] >= 0.9
    assert scout["bbox_area_frac"] < 0.6
    assert result["baseline"]["overall"]["bbox_hit_rate"] is None
    on_disk = json.loads((tmp_path / "eval" / "scout.json").read_text())
    assert on_disk["scout"]["overall"] == scout
    saved = MdnScout.load(tmp_path / "eval" / "scout.pt")
    assert saved.config == ScoutConfig()
    assert saved.radio_map_sha256 == hashlib.sha256(
        (tmp_path / "eval" / "radio_map.json").read_bytes()).hexdigest()


def test_bbox_holds_the_clipped_mean_when_the_mean_is_outside_the_room():
    # Kernel means are unconstrained network outputs; a far, light kernel can
    # drag the mixture mean past a wall. The box then holds its nearest
    # in-room point rather than losing it to clipping.
    # The far kernel is too light to be in the densest 95 %, so only the
    # mean can stretch the box to the wall.
    mixture = Mixture(weights=np.array([0.96, 0.04, 0.0]),
                      means=np.array([[1.0, 1.0], [100.0, 1.0], [1.0, 1.0]]),
                      sds=np.full((3, 2), 0.1))
    assert mixture.mean()[0] > ROOM[0]  # 4.96 m, beyond the 4 m wall
    x0, y0, x1, y1 = bbox(mixture, ROOM)
    assert x0 < 1.0 and x1 == ROOM[0]
    assert y0 <= 1.0 <= y1 < 1.5


def test_training_is_deterministic_given_a_seed():
    rssi, xy = _toy_set()
    runs = [MdnScout(ANCHORS, room=ROOM, config=ScoutConfig(epochs=50, seed=3)).fit(rssi, xy)
            for _ in range(2)]
    assert runs[0] == runs[1]
