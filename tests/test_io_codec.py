"""JSONL trial-data codec round-trip: tuples, numpy, float rounding, header."""

from __future__ import annotations

import numpy as np

from murineshiftwork.io import MSW_FILE_VERSION, load_trial_data, save_trial_data


def test_roundtrip_preserves_basic_values(tmp_path):
    trials = [{"trial": 1, "outcome": "hit"}, {"trial": 2, "outcome": "miss"}]
    p = tmp_path / "out.jsonl"
    save_trial_data(trials, p)
    assert load_trial_data(p) == trials


def test_version_header_written_and_skipped(tmp_path):
    p = tmp_path / "out.jsonl"
    save_trial_data([{"a": 1}], p)
    first = p.read_text().splitlines()[0]
    assert MSW_FILE_VERSION in first  # header line carries the version
    loaded = load_trial_data(p)
    assert loaded == [{"a": 1}]  # header is not returned as a trial


def test_tuples_survive_roundtrip(tmp_path):
    trials = [{"block_type_values": (0, 1), "nested": [(1, 2), (3, 4)]}]
    p = tmp_path / "out.jsonl"
    save_trial_data(trials, p)
    loaded = load_trial_data(p)
    assert loaded[0]["block_type_values"] == (0, 1)
    assert isinstance(loaded[0]["block_type_values"], tuple)
    assert loaded[0]["nested"] == [(1, 2), (3, 4)]
    assert all(isinstance(t, tuple) for t in loaded[0]["nested"])


def test_numpy_arrays_become_lists(tmp_path):
    trials = [{"arr": np.array([1, 2, 3]), "farr": np.array([1.111111, 2.222222])}]
    p = tmp_path / "out.jsonl"
    save_trial_data(trials, p)
    loaded = load_trial_data(p)
    assert loaded[0]["arr"] == [1, 2, 3]
    # floats rounded to 4 dp on the way out
    assert loaded[0]["farr"] == [1.1111, 2.2222]


def test_numpy_scalars_encoded(tmp_path):
    trials = [{"i": np.int64(7), "f": np.float64(3.14159265), "b": np.bool_(True)}]
    p = tmp_path / "out.jsonl"
    save_trial_data(trials, p)
    loaded = load_trial_data(p)
    assert loaded[0] == {"i": 7, "f": 3.1416, "b": True}


def test_floats_rounded_to_four_dp(tmp_path):
    trials = [{"x": 0.123456789}]
    p = tmp_path / "out.jsonl"
    save_trial_data(trials, p)
    assert load_trial_data(p)[0]["x"] == 0.1235


def test_save_creates_parent_dirs(tmp_path):
    p = tmp_path / "nested" / "deeper" / "out.jsonl"
    save_trial_data([{"a": 1}], p)
    assert p.exists()


def test_load_skips_blank_lines(tmp_path):
    p = tmp_path / "out.jsonl"
    save_trial_data([{"a": 1}], p)
    p.write_text(p.read_text() + "\n\n")  # trailing blanks
    assert load_trial_data(p) == [{"a": 1}]


def test_empty_trial_list_roundtrips(tmp_path):
    p = tmp_path / "out.jsonl"
    save_trial_data([], p)
    assert load_trial_data(p) == []
