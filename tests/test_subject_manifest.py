"""Tests for the subject-level manifest writers (chronic probe insertions)."""

from __future__ import annotations

import pytest

from murineshiftwork.namespace import manifest as m

SUBJECT = "t004_m2045"
DT = "20260514_143022_123456"


def _make_tree(root):
    """Create basepath/{subject}/{container}/{acquisition} and return (subject_dir, acq)."""
    acq = root / SUBJECT / f"{SUBJECT}__{DT}" / f"{SUBJECT}__{DT}__msw__sequence"
    acq.mkdir(parents=True)
    return root / SUBJECT, acq


def test_path_helpers_and_resolution(tmp_path):
    subject_dir, acq = _make_tree(tmp_path)
    assert m.subject_manifest_path(tmp_path, SUBJECT) == subject_dir / "subject_manifest.yaml"
    # resolve from a deep acquisition path...
    assert m.subject_dir_for(acq) == subject_dir
    # ...and from the subject dir itself (valid structured subject name).
    assert m.subject_dir_for(subject_dir) == subject_dir


def test_init_stamps_type_version_and_fields(tmp_path):
    subject_dir, _ = _make_tree(tmp_path)
    m.init_subject_manifest(subject_dir, SUBJECT)
    data = m.read_subject_manifest(subject_dir)
    assert data["type"] == "subject"
    assert data["subject"] == SUBJECT
    assert data["msw_namespace_version"] == m._namespace_version()
    assert data["subject_fields"] == {"subject_id": "t004", "animal_id": "m2045", "tag_id": None}
    assert data["probe_insertions"] == []


def test_append_is_upsert_by_id(tmp_path):
    subject_dir, acq = _make_tree(tmp_path)
    m.append_probe_insertion(subject_dir, {"id": "21290000", "target": "CA1"})
    m.append_probe_insertion(subject_dir, {"id": "21290000", "coordinates": {"ap": -2.0}})
    m.append_probe_insertion(subject_dir, {"id": "shankB", "target": "V1"})
    data = m.read_subject_manifest(acq)
    assert len(data["probe_insertions"]) == 2  # not 3
    first = next(r for r in data["probe_insertions"] if r["id"] == "21290000")
    assert first["target"] == "CA1" and first["coordinates"] == {"ap": -2.0}
    assert first["status"] == "active" and first["explanted_at"] is None


def test_append_requires_id(tmp_path):
    subject_dir, _ = _make_tree(tmp_path)
    with pytest.raises(ValueError):
        m.append_probe_insertion(subject_dir, {"target": "CA1"})


def test_finalize_marks_explanted(tmp_path):
    subject_dir, _ = _make_tree(tmp_path)
    m.append_probe_insertion(subject_dir, {"id": "21290000"})
    m.finalize_probe_insertion(subject_dir, "21290000")
    rec = m.read_subject_manifest(subject_dir)["probe_insertions"][0]
    assert rec["status"] == "explanted" and rec["explanted_at"] is not None


def test_unstructured_subject_has_no_fields(tmp_path):
    """A non-parseable subject still works, just without subject_fields."""
    subject = "weird-subject-name"
    subject_dir = tmp_path / subject
    subject_dir.mkdir()
    m.append_probe_insertion(subject_dir, {"id": "x"})
    data = m.read_subject_manifest(subject_dir)
    assert "subject_fields" not in data
    assert data["subject"] == subject and len(data["probe_insertions"]) == 1


def test_read_absent_returns_none(tmp_path):
    subject_dir, _ = _make_tree(tmp_path)
    assert m.read_subject_manifest(subject_dir) is None  # never created


def test_set_subject_metadata_merges(tmp_path):
    subject_dir, _ = _make_tree(tmp_path)
    m.set_subject_metadata(subject_dir, {"colony_id": "abc"})
    m.set_subject_metadata(subject_dir, {"line": "PV-Cre"})
    md = m.read_subject_manifest(subject_dir)["metadata"]
    assert md == {"colony_id": "abc", "line": "PV-Cre"}
