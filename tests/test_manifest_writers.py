"""Manifest writer lifecycle + round-trip through the container reader.

Covers the write side of the IO contract: session/acquisition manifest creation,
acquisition + subprotocol append/finalize, and that what the writers produce is
read back consistently by enumerate_acquisitions / validate_session_container.
"""

from __future__ import annotations

import yaml

from murineshiftwork.namespace.manifest import (
    append_acquisition_to_session,
    append_subprotocol,
    finalize_acquisition_in_session,
    finalize_subprotocol,
    init_acquisition_manifest,
    init_session_manifest,
)
from murineshiftwork.readers import enumerate_acquisitions, validate_session_container

_BEHAV = "s1__20260620_120000_000000__sequence__v1"


def _read(p):
    return yaml.safe_load(p.read_text()) or {}


# --- session manifest ---


def test_init_session_manifest_creates_stamped_file(tmp_path):
    init_session_manifest(tmp_path, "host_session_x")
    data = _read(tmp_path / "session_manifest.yaml")
    assert data["type"] == "session"
    assert data["session_name"] == "host_session_x"
    assert data["acquisitions"] == []
    assert data["msw_manifest_version"] == 1
    assert data["msw_namespace_version"]  # stamped with the spec version


def test_init_session_manifest_is_idempotent(tmp_path):
    init_session_manifest(tmp_path, "first")
    init_session_manifest(tmp_path, "second")  # must not overwrite
    assert _read(tmp_path / "session_manifest.yaml")["session_name"] == "first"


def test_append_acquisition_then_finalize(tmp_path):
    init_session_manifest(tmp_path, "host")
    append_acquisition_to_session(tmp_path, _BEHAV, started_at="2026-06-20T12:00:00")
    entry = _read(tmp_path / "session_manifest.yaml")["acquisitions"][0]
    assert entry["basename"] == _BEHAV
    assert entry["status"] == "running"
    assert entry["started_at"] == "2026-06-20T12:00:00"
    assert entry["ended_at"] is None

    finalize_acquisition_in_session(tmp_path, _BEHAV, status="complete")
    entry = _read(tmp_path / "session_manifest.yaml")["acquisitions"][0]
    assert entry["status"] == "complete"
    assert entry["ended_at"] is not None


def test_append_acquisition_is_deduplicated(tmp_path):
    append_acquisition_to_session(tmp_path, _BEHAV)
    append_acquisition_to_session(tmp_path, _BEHAV)  # same basename, no dup
    acqs = _read(tmp_path / "session_manifest.yaml")["acquisitions"]
    assert [a["basename"] for a in acqs] == [_BEHAV]


def test_append_acquisition_creates_manifest_when_absent(tmp_path):
    # no init first: append must create a usable session manifest
    append_acquisition_to_session(tmp_path, _BEHAV)
    assert (tmp_path / "session_manifest.yaml").exists()
    assert _read(tmp_path / "session_manifest.yaml")["acquisitions"][0]["basename"] == (
        _BEHAV
    )


def test_finalize_missing_acquisition_is_noop(tmp_path):
    init_session_manifest(tmp_path, "host")
    finalize_acquisition_in_session(tmp_path, "nonexistent__acq")  # must not raise
    assert _read(tmp_path / "session_manifest.yaml")["acquisitions"] == []


# --- acquisition manifest + subprotocols ---


def test_init_acquisition_manifest_with_metadata(tmp_path):
    acq = tmp_path / _BEHAV
    acq.mkdir()
    init_acquisition_manifest(
        acq, _BEHAV, metadata={"source": "legacy_matlab", "legacy_subject": "old01"}
    )
    data = _read(acq / "acquisition_manifest.yaml")
    assert data["type"] == "acquisition"
    assert data["acquisition_name"] == _BEHAV
    assert data["subprotocols"] == []
    assert data["metadata"]["source"] == "legacy_matlab"


def test_subprotocol_append_then_finalize(tmp_path):
    acq = tmp_path / _BEHAV
    acq.mkdir()
    init_acquisition_manifest(acq, _BEHAV)
    append_subprotocol(acq, "power_ramp", "ramp.msw.df.jsonl", barcode_start=10)
    sp = _read(acq / "acquisition_manifest.yaml")["subprotocols"][0]
    assert sp["name"] == "power_ramp"
    assert sp["file"] == "ramp.msw.df.jsonl"
    assert sp["barcode_start"] == 10
    assert sp["status"] == "running"

    finalize_subprotocol(acq, "power_ramp", barcode_end=42, status="complete")
    sp = _read(acq / "acquisition_manifest.yaml")["subprotocols"][0]
    assert sp["barcode_end"] == 42
    assert sp["status"] == "complete"


# --- write -> read round-trip ---


def test_written_manifest_reconciles_with_reader(tmp_path):
    # build a container the way TaskProcess does, then read it back
    (tmp_path / _BEHAV).mkdir()
    init_session_manifest(tmp_path, "host")
    append_acquisition_to_session(tmp_path, _BEHAV)
    finalize_acquisition_in_session(tmp_path, _BEHAV)

    infos = {i.basename: i for i in enumerate_acquisitions(tmp_path)}
    assert _BEHAV in infos
    assert infos[_BEHAV].in_manifest is True
    assert infos[_BEHAV].on_disk is True
    assert infos[_BEHAV].status == "complete"

    report = validate_session_container(tmp_path)
    assert report.is_consistent is True
