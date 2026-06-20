"""readers.files loaders: json, settings.py, and trial-df (jsonl) parsing."""

from __future__ import annotations

import pandas as pd

from murineshiftwork.io import save_trial_data
from murineshiftwork.readers.files import read_json, read_settings_py, read_trial_df


def test_read_json(tmp_path):
    p = tmp_path / "x.json"
    p.write_text('{"a": 1, "b": [2, 3]}')
    assert read_json(p) == {"a": 1, "b": [2, 3]}


def test_read_settings_py(tmp_path):
    p = tmp_path / "settings.py"
    p.write_text("FOO = 1\nBAR = 'two'\n")
    out = read_settings_py(p)
    assert out["FOO"] == 1
    assert out["BAR"] == "two"
    assert "__builtins__" not in out  # dunder-prefixed names filtered out


def _trial(i):
    # realistic Bpod trial so the non-raw path (info/States/Events) succeeds
    return {
        "trial": i,
        "info": {"outcome": "hit"},
        "States timestamps": {"choice": [[0.1, 0.2]]},
        "Events timestamps": {"Port1In": [0.15]},
    }


def test_read_trial_df_jsonl_raw(tmp_path):
    p = tmp_path / "s.msw.df.jsonl"
    save_trial_data([_trial(1), _trial(2)], p)
    df = read_trial_df(p, return_raw=True)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert "info" in df.columns  # raw keeps the nested dict column


def test_read_trial_df_jsonl_expanded(tmp_path):
    p = tmp_path / "s.msw.df.jsonl"
    save_trial_data([_trial(1), _trial(2)], p)
    df = read_trial_df(p)  # non-raw expands info/States/Events
    assert "outcome" in df.columns  # info dict expanded into columns
    assert "info" not in df.columns


def test_read_trial_df_empty_returns_none(tmp_path):
    p = tmp_path / "empty.msw.df.jsonl"
    save_trial_data([], p)
    assert read_trial_df(p) is None
