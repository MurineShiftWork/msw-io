"""Self-contained unit tests for readers.alignment.

The existing test_ephys_barcode_alignment.py is gated on a checked-in fixture;
these exercise the decode/guard/matching logic directly (with monkeypatched
session + barcode decode) so the alignment code is covered without that fixture.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("ttl_barcoder")

from murineshiftwork.readers import alignment  # noqa: E402
from murineshiftwork.readers.alignment import (  # noqa: E402
    align_session_to_ephys,
    decode_ephys_barcodes,
    decode_rpi_ttl_in,
    verify_rpi_barcode_decoding,
)

_FIRST_STATE = "barcode_start"


# --- decode helpers on degenerate input ---


def test_decode_ephys_barcodes_no_matching_line():
    events = pd.DataFrame({"line": [1, 1], "timestamps": [0.0, 0.1], "state": [1, 0]})
    assert decode_ephys_barcodes(events, barcode_bnc_line=2) == []


def test_decode_ephys_barcodes_too_few_edges():
    # fewer than 6 edges in the only segment -> nothing decoded
    events = pd.DataFrame(
        {"line": [2, 2, 2], "timestamps": [0.0, 0.01, 0.02], "state": [1, 0, 1]}
    )
    assert decode_ephys_barcodes(events, barcode_bnc_line=2) == []


def test_decode_rpi_ttl_in_empty(tmp_path):
    p = tmp_path / "ttl_in.npz"
    np.savez(p, timestamp=np.array([]), data=np.array([]))
    assert decode_rpi_ttl_in(p) == []


# --- align_session_to_ephys guards (monkeypatched session df) ---


def _patch_df(monkeypatch, df):
    monkeypatch.setattr(alignment, "read_session_data", lambda _sd: {"df": df})


def test_align_raises_without_df(monkeypatch):
    _patch_df(monkeypatch, None)
    with pytest.raises(ValueError, match="trial df"):
        align_session_to_ephys("x", pd.DataFrame(), barcode_bnc_line=2)


def test_align_raises_without_barcode_column(monkeypatch):
    _patch_df(monkeypatch, pd.DataFrame({"Trial start timestamp": [1.0]}))
    with pytest.raises(ValueError, match="barcode_value"):
        align_session_to_ephys("x", pd.DataFrame(), barcode_bnc_line=2)


def test_align_raises_without_barcode_trials(monkeypatch):
    df = pd.DataFrame({"barcode_value": [None], "Trial start timestamp": [1.0]})
    _patch_df(monkeypatch, df)
    with pytest.raises(ValueError, match="No barcode trials"):
        align_session_to_ephys("x", pd.DataFrame(), barcode_bnc_line=2)


def test_align_happy_path(monkeypatch):
    df = pd.DataFrame(
        {
            "barcode_value": [5, 7],
            _FIRST_STATE: [[[0.1, 0.2]], [[1.1, 1.2]]],
            "Trial start timestamp": [10.0, 20.0],
        }
    )
    _patch_df(monkeypatch, df)
    # bpod barcode times are 10.1 and 21.1; map them to ephys 100.0 and 111.0
    monkeypatch.setattr(
        alignment,
        "decode_ephys_barcodes",
        lambda **_: [(100.0, 5), (111.0, 7)],
    )
    out_df, result = align_session_to_ephys("x", pd.DataFrame(), barcode_bnc_line=2)

    assert result["n_matched"] == 2
    assert result["slope"] == pytest.approx(1.0, abs=1e-6)
    assert result["intercept"] == pytest.approx(89.9, abs=1e-6)
    # alignment columns written back onto the df
    assert "trial_start_ephys" in out_df.columns
    assert out_df["trial_start_ephys"].iloc[0] == pytest.approx(99.9, abs=1e-6)
    # the mapping function round-trips an anchor
    assert result["bpod_to_ephys"](10.1) == pytest.approx(100.0, abs=1e-6)


# --- verify_rpi_barcode_decoding (monkeypatched session + rpi decode) ---


def test_verify_rpi_raises_without_barcode_column(monkeypatch):
    _patch_df(monkeypatch, pd.DataFrame({"trial": [1]}))
    with pytest.raises(ValueError, match="barcode_value"):
        verify_rpi_barcode_decoding("x", "ttl.npz")


def test_verify_rpi_match_stats(monkeypatch):
    df = pd.DataFrame(
        {
            "barcode_value": [5, 7],
            "barcode_wall_time": [1000.0, 1001.0],
        }
    )
    _patch_df(monkeypatch, df)
    # rpi decodes both, offset by +100 ms and +200 ms respectively
    monkeypatch.setattr(
        alignment,
        "decode_rpi_ttl_in",
        lambda *_a, **_k: [(1000.1, 5), (1001.2, 7)],
    )
    result = verify_rpi_barcode_decoding("x", "ttl.npz")

    assert result["n_msw_barcodes"] == 2
    assert result["n_matched"] == 2
    assert result["match_rate"] == pytest.approx(1.0)
    assert result["wall_time_error_max_ms"] == pytest.approx(200.0, abs=1e-3)
    assert result["unmatched_msw_values"] == []
