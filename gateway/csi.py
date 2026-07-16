"""CSI amplitude processing: subcarrier remap, normalization, aggregation,
and the D-CFR (differential CFR) transform from the methodology chapter.

Hardware buffer order (ESP32 LLTF, 64-FFT, per firmware/README.md):
entry i for i in 0..31 holds subcarrier +i; entry i for i in 32..63 holds
subcarrier i-64 (i.e. -32..-1). The textbook usable data subcarriers are
-26..-1 and +1..+26 (52 values); DC (entry 0) and the guard band (entries
27..37) are null and dropped.

first_word_invalid: the ESP32 marks the first CSI *word* (hardware indices
0 and 1) invalid. Index 0 is DC (dropped anyway); index 1 is subcarrier +1.
Real captures confirm it — index 1 reads ~3 while its neighbors read ~25 —
so by default we also drop subcarrier +1, leaving 51 usable subcarriers and
50 D-CFR differentials. Set drop_first_pos=False to keep the textbook 52/51
layout (e.g. to match the methodology text verbatim).
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

DROP_FIRST_POS_DEFAULT = True

NORM_METHODS = ("l2", "center", "none")


def usable_subcarriers(drop_first_pos: bool = DROP_FIRST_POS_DEFAULT) -> List[int]:
    positive = range(2, 27) if drop_first_pos else range(1, 27)
    return list(range(-26, 0)) + list(positive)


def hw_to_usable_indices(drop_first_pos: bool = DROP_FIRST_POS_DEFAULT) -> np.ndarray:
    """Permutation from 64-entry hardware buffer order to usable-subcarrier
    order (-26..+26, ascending). Default drops the corrupt subcarrier +1."""
    return np.array(
        [k + 64 if k < 0 else k for k in usable_subcarriers(drop_first_pos)],
        dtype=np.intp,
    )


# Module-level defaults reflect the recommended (drop) layout: 51 usable, 50 D-CFR.
USABLE_SUBCARRIERS = usable_subcarriers()
HW_TO_USABLE = hw_to_usable_indices()
N_USABLE = len(USABLE_SUBCARRIERS)  # 51 by default
N_DCFR = N_USABLE - 1               # 50 by default


def remap_hw64_to_usable(
    amps64: np.ndarray, hw_indices: Optional[np.ndarray] = None
) -> np.ndarray:
    """64 hardware-order amplitudes -> usable subcarriers in ascending order.
    Pass hw_indices from hw_to_usable_indices(...) to override the default."""
    amps64 = np.asarray(amps64)
    if amps64.shape != (64,):
        raise ValueError(f"expected shape (64,), got {amps64.shape}")
    idx = HW_TO_USABLE if hw_indices is None else hw_indices
    return amps64[idx]


def is_valid_csi(csi: np.ndarray) -> bool:
    """Reject all-zero or non-finite spectra (dead capture / glitch)."""
    return bool(np.all(np.isfinite(csi)) and np.any(csi != 0))


def normalize(csi: np.ndarray, method: str = "l2") -> np.ndarray:
    """Per-packet normalization. Default L2 unit-norm: ESP32 amplitudes are
    post-AGC so absolute scale is meaningless per packet; unit-norm removes
    scale while preserving the spectral shape that D-CFR/Pearson matching
    relies on."""
    csi = np.asarray(csi, dtype=np.float64)
    if method == "l2":
        norm = np.linalg.norm(csi)
        return csi / norm if norm > 0 else csi
    if method == "center":
        return csi - csi.mean()
    if method == "none":
        return csi
    raise ValueError(f"unknown normalization method {method!r}")


def aggregate(csi_list: List[np.ndarray], how: str = "median") -> np.ndarray:
    """Combine the packets of one (window, mac, anchor) group into one
    spectrum. Median is robust to single-packet fades."""
    stack = np.stack(csi_list)
    if how == "median":
        return np.median(stack, axis=0)
    if how == "mean":
        return stack.mean(axis=0)
    raise ValueError(f"unknown aggregation {how!r}")


def dcfr(h: np.ndarray) -> np.ndarray:
    """Differential CFR: adjacent-subcarrier amplitude differences
    (methodology Eq. for ΔH). Cancels hardware offsets that affect adjacent
    frequencies nearly identically; what remains is multipath shape.

    The position spanning the -1 -> +2 DC gap is harmless because stored
    fingerprints use the identical convention."""
    h = np.asarray(h, dtype=np.float64)
    return np.diff(h)


def process_window_csi(
    amps_hw_list: List[np.ndarray],
    norm_method: str = "l2",
    hw_indices: Optional[np.ndarray] = None,
) -> Tuple[Optional[np.ndarray], int]:
    """Full per-(window, mac, anchor) chain: remap each packet, drop invalid
    spectra, normalize, aggregate by median. Returns (aggregated spectrum or
    None, number of packets whose CSI survived validation)."""
    idx = HW_TO_USABLE if hw_indices is None else hw_indices
    valid = []
    for amps in amps_hw_list:
        csi = remap_hw64_to_usable(amps, idx)
        if is_valid_csi(csi):
            valid.append(normalize(csi, norm_method))
    if not valid:
        return None, 0
    return aggregate(valid, "median"), len(valid)
