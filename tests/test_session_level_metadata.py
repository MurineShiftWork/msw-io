"""Session-level manifest metadata (e.g. reward) surfaces when loading an acquisition.

Reward and similar session-level facts live once on the container's session_manifest,
not duplicated per acquisition; the reader composes them for each acquisition.
"""

from __future__ import annotations

import yaml

from murineshiftwork.readers.session import _read_metadata

DT = "20260514_143022_123456"
SUBJECT = "t004_m2045"


def _tree(tmp_path):
    container = tmp_path / f"{SUBJECT}__{DT}"
    acq = container / f"{SUBJECT}__{DT}__msw__sequence"
    acq.mkdir(parents=True)
    return container, acq


def test_session_level_metadata_surfaces_per_acquisition(tmp_path):
    container, acq = _tree(tmp_path)
    container.joinpath("session_manifest.yaml").write_text(
        yaml.dump({"type": "session", "metadata": {"reward": {"type": "milkshake"}}})
    )
    acq.joinpath("acquisition_manifest.yaml").write_text(
        yaml.dump({"type": "acquisition", "metadata": {"source": "native"}})
    )
    md = _read_metadata(acq)
    assert md["reward"] == {"type": "milkshake"}  # from the PARENT session manifest
    assert md["source"] == "native"               # acquisition-level preserved


def test_acquisition_level_overrides_session_level(tmp_path):
    container, acq = _tree(tmp_path)
    container.joinpath("session_manifest.yaml").write_text(
        yaml.dump({"metadata": {"k": "session"}})
    )
    acq.joinpath("acquisition_manifest.yaml").write_text(
        yaml.dump({"metadata": {"k": "acquisition"}})
    )
    assert _read_metadata(acq)["k"] == "acquisition"


def test_no_metadata_returns_none(tmp_path):
    _, acq = _tree(tmp_path)
    assert _read_metadata(acq) is None
