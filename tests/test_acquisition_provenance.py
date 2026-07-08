"""Acquisition-level provenance (task schema version + reward) surfaces on load.

Both the task-schema stamp and the reward config follow the acquisition, so they live
on the acquisition manifest and the reader surfaces them as MswSession.metadata.
"""

from __future__ import annotations

import yaml

from murineshiftwork.readers.session import _read_metadata

DT = "20260514_143022_123456"
SUBJECT = "t004_m2045"


def test_acquisition_metadata_surfaces(tmp_path):
    acq = tmp_path / f"{SUBJECT}__{DT}" / f"{SUBJECT}__{DT}__msw__sequence"
    acq.mkdir(parents=True)
    acq.joinpath("acquisition_manifest.yaml").write_text(
        yaml.dump(
            {
                "type": "acquisition",
                "metadata": {
                    "task": {
                        "task": "sequence",
                        "task_schema_version": 1,
                        "scoring_metric": "ordered",
                    },
                    "reward": {"type": "water"},
                },
            }
        )
    )
    md = _read_metadata(acq)
    assert md["task"] == {
        "task": "sequence",
        "task_schema_version": 1,
        "scoring_metric": "ordered",
    }
    assert md["reward"] == {"type": "water"}


def test_no_metadata_returns_none(tmp_path):
    acq = tmp_path / "c" / "a"
    acq.mkdir(parents=True)
    assert _read_metadata(acq) is None
