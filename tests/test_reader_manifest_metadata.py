"""Manifest-led reading, optional metadata, and the external ingest API.

Covers the reader's manifest-first tier (so a transformed legacy-MATLAB dataset
of manifest + .msw.df.jsonl loads), the optional MswSession.metadata block, and
the public manifest-writing entry point an out-of-suite ingest tool uses.
"""

from pathlib import Path

import yaml

from murineshiftwork.io import save_trial_data
from murineshiftwork.namespace import (
    set_manifest_metadata,
    write_acquisition_manifest_for_ingest,
)
from murineshiftwork.readers.batch import load_session
from murineshiftwork.readers.namespace import (
    ARTIFACT_FORMAT_LEGACY,
    ARTIFACT_FORMAT_MANIFEST,
    ARTIFACT_FORMAT_SESSION_YAML,
    detect_artifact_format,
)

_BASENAME = "m0000001__20260101_120000_000000__sequence"
# Minimal but structurally-real Bpod trial dicts (read_trial_df expands the
# info / States timestamps / Events timestamps dict columns).
_TRIALS = [
    {
        "info": {"trial_num": 0, "outcome": "correct"},
        "States timestamps": {"reward": [[0.10, 0.20]]},
        "Events timestamps": {"Port2In": [0.05]},
    },
    {
        "info": {"trial_num": 1, "outcome": "incorrect"},
        "States timestamps": {"punish": [[0.30, 0.40]]},
        "Events timestamps": {"Port1In": [0.15]},
    },
]


def _write_jsonl(d: Path) -> None:
    save_trial_data(_TRIALS, d / f"{_BASENAME}.msw.df.jsonl")


def test_transformed_legacy_matlab_loads_via_manifest(tmp_path):
    """Manifest + jsonl (no session.yaml) loads, with legacy provenance metadata."""
    d = tmp_path / _BASENAME
    d.mkdir()
    _write_jsonl(d)
    write_acquisition_manifest_for_ingest(
        d,
        _BASENAME,
        metadata={
            "source": "legacy_matlab",
            "legacy_subject": "OldMouse_42",
            "legacy_structure": "Sequence_Automated",
        },
    )

    assert detect_artifact_format(d) == ARTIFACT_FORMAT_MANIFEST
    s = load_session(d)
    assert s.df is not None and len(s.df) == 2
    assert s.artifact_format == ARTIFACT_FORMAT_MANIFEST
    assert s.is_complete is True  # df present is enough for a transformed dataset
    assert s.metadata is not None
    assert s.metadata["source"] == "legacy_matlab"
    assert s.metadata["legacy_subject"] == "OldMouse_42"


def test_native_session_with_manifest_stays_session_yaml(tmp_path):
    """A native session keeps artifact_format session_yaml even with a manifest."""
    d = tmp_path / _BASENAME
    d.mkdir()
    _write_jsonl(d)
    (d / f"{_BASENAME}.msw.session.yaml").write_text(
        yaml.safe_dump({"msw_format_version": 2, "task_settings": {"x": 1}})
    )
    write_acquisition_manifest_for_ingest(d, _BASENAME)  # manifest co-present
    assert detect_artifact_format(d) == ARTIFACT_FORMAT_SESSION_YAML


def test_metadata_roundtrip_set_then_read(tmp_path):
    """set_manifest_metadata stamps a manifest; the reader surfaces it."""
    d = tmp_path / _BASENAME
    d.mkdir()
    _write_jsonl(d)
    write_acquisition_manifest_for_ingest(d, _BASENAME)
    set_manifest_metadata(
        d / "acquisition_manifest.yaml", {"source": "legacy_matlab", "rig": "fixture"}
    )
    s = load_session(d)
    assert s.metadata["source"] == "legacy_matlab"
    assert s.metadata["rig"] == "fixture"


def test_dispatch_tiers(tmp_path):
    """Latest-first dispatch: session.yaml > manifest > jsonl-degraded > legacy."""
    # manifest only (no session.yaml) -> manifest
    a = tmp_path / "a"
    a.mkdir()
    _write_jsonl(a)
    write_acquisition_manifest_for_ingest(a, _BASENAME)
    assert detect_artifact_format(a) == ARTIFACT_FORMAT_MANIFEST

    # bare jsonl, no manifest/session.yaml -> degraded namespace (session_yaml)
    b = tmp_path / "b"
    b.mkdir()
    _write_jsonl(b)
    assert detect_artifact_format(b) == ARTIFACT_FORMAT_SESSION_YAML

    # legacy pkl markers -> legacy
    c = tmp_path / "c"
    c.mkdir()
    (c / "task_settings.py").write_text("settings = {}\n")
    (c / "switching.pkl").write_bytes(b"")
    assert detect_artifact_format(c) == ARTIFACT_FORMAT_LEGACY
