"""End-to-end: synthetic session -> preprocess -> assert against ground truth."""

from __future__ import annotations

import json

import numpy as np
import pytest

from gateway.csi import dcfr, normalize, remap_hw64_to_usable
from gateway.preprocess import PreprocessConfig, run
from gateway.synth import generate


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    outdir = tmp_path_factory.mktemp("synth")
    truth = generate(
        outdir,
        duration_s=20.0,
        rate_hz=20.0,
        dropouts=[("A3", 5.0, 10.0), ("A4", 5.0, 10.0)],
        malformed_frac=0.02,
        seed=7,
    )
    return outdir, truth


def _run(outdir, tmp_path, **overrides):
    cfg = PreprocessConfig(
        inputs=[outdir],
        out=tmp_path / "windows.jsonl",
        **overrides,
    )
    summary = run(cfg)
    lines = (tmp_path / "windows.jsonl").read_text().splitlines()
    meta = json.loads(lines[0])["_meta"]
    features = [json.loads(l) for l in lines[1:]]
    return summary, meta, features


def test_malformed_count_matches_injection(session, tmp_path):
    outdir, truth = session
    summary, _, _ = _run(outdir, tmp_path)
    expected = sum(truth["malformed_per_anchor"].values())
    assert summary["parse"]["malformed"] == expected


def test_usable_window_rate_reflects_dropout(session, tmp_path):
    outdir, truth = session
    summary, _, features = _run(outdir, tmp_path)

    # During 5-10s two anchors are silent -> only 2 of 4 -> insufficient.
    insufficient = [f for f in features if not f["sufficient"]]
    assert insufficient, "dropout interval should produce insufficient windows"
    for f in insufficient:
        assert f["anchors"]["A3"] is None
        assert f["anchors"]["A4"] is None
    assert 0 < summary["windows"]["usable_window_rate"] < 1


def test_rssi_close_to_ground_truth(session, tmp_path):
    outdir, truth = session
    _, _, features = _run(outdir, tmp_path)
    mac = truth["macs"][0]
    values = [
        f["anchors"]["A1"]["rssi"]
        for f in features
        if f["mac"] == mac and f["anchors"]["A1"]
    ]
    assert values
    assert np.mean(values) == pytest.approx(truth["rssi_means"]["A1"][mac], abs=1.5)


def test_dcfr_matches_template(session, tmp_path):
    outdir, truth = session
    _, _, features = _run(outdir, tmp_path)
    mac = truth["macs"][0]
    template = np.array(truth["templates_hw"]["A1"][mac])
    expected = dcfr(normalize(remap_hw64_to_usable(template)))

    recovered = [
        np.array(f["anchors"]["A1"]["dcfr"])
        for f in features
        if f["mac"] == mac and f["anchors"]["A1"] and f["anchors"]["A1"]["dcfr"]
    ]
    assert recovered
    mean_dcfr = np.mean(recovered, axis=0)
    rho = np.corrcoef(mean_dcfr, expected)[0, 1]
    assert rho > 0.95


def test_meta_records_run_config(session, tmp_path):
    outdir, _ = session
    _, meta, _ = _run(outdir, tmp_path, window_s=0.5, min_anchors=2)
    assert meta["window_s"] == 0.5
    assert meta["min_anchors"] == 2
    assert meta["csi_norm"] == "l2"
    assert "t0" in meta
