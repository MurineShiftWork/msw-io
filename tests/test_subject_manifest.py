"""Tests for the general subject-level manifest (domain-agnostic key-value store)."""

from __future__ import annotations

from murineshiftwork.namespace import manifest as m

SUBJECT = "t004_m2045"
DT = "20260514_143022_123456"


def _make_tree(root):
    """Create basepath/{subject}/{container}/{acquisition}; return (subject_dir, acq)."""
    acq = root / SUBJECT / f"{SUBJECT}__{DT}" / f"{SUBJECT}__{DT}__msw__sequence"
    acq.mkdir(parents=True)
    return root / SUBJECT, acq


def test_path_helpers_and_resolution(tmp_path):
    subject_dir, acq = _make_tree(tmp_path)
    assert m.subject_manifest_path(tmp_path, SUBJECT) == subject_dir / "subject_manifest.yaml"
    assert m.subject_dir_for(acq) == subject_dir          # from a deep acquisition path
    assert m.subject_dir_for(subject_dir) == subject_dir  # from the subject dir itself


def test_init_stamps_type_version_and_fields(tmp_path):
    subject_dir, _ = _make_tree(tmp_path)
    m.init_subject_manifest(subject_dir, SUBJECT)
    data = m.read_subject_manifest(subject_dir)
    assert data["type"] == "subject"
    assert data["subject"] == SUBJECT
    assert data["msw_namespace_version"] == m._namespace_version()
    assert data["subject_fields"] == {"subject_id": "t004", "animal_id": "m2045", "tag_id": None}
    # domain-agnostic: no baked-in categories like probe_insertions
    assert "probe_insertions" not in data


def test_update_merges_arbitrary_keys_and_creates_if_absent(tmp_path):
    subject_dir, acq = _make_tree(tmp_path)
    # an addon owns its own key shape; the manifest just stores it
    m.update_subject_manifest(subject_dir, {"probe_insertions": [{"id": "21290000"}]})
    m.update_subject_manifest(subject_dir, {"weight_log": [{"g": 24.1}]})
    data = m.read_subject_manifest(acq)
    assert data["type"] == "subject"  # created on first update
    assert data["probe_insertions"] == [{"id": "21290000"}]
    assert data["weight_log"] == [{"g": 24.1}]
    assert "updated_at" in data


def test_update_replaces_key_read_modify_write(tmp_path):
    subject_dir, _ = _make_tree(tmp_path)
    m.update_subject_manifest(subject_dir, {"items": [1]})
    data = m.read_subject_manifest(subject_dir)
    m.update_subject_manifest(subject_dir, {"items": [*data["items"], 2]})  # accumulate
    assert m.read_subject_manifest(subject_dir)["items"] == [1, 2]


def test_set_subject_metadata_merges(tmp_path):
    subject_dir, _ = _make_tree(tmp_path)
    m.set_subject_metadata(subject_dir, {"colony_id": "abc"})
    m.set_subject_metadata(subject_dir, {"line": "PV-Cre"})
    assert m.read_subject_manifest(subject_dir)["metadata"] == {"colony_id": "abc", "line": "PV-Cre"}


def test_set_subject_metadata_deep_merges_key_trees(tmp_path):
    """Addons insert nested subtrees under metadata without clobbering siblings."""
    subject_dir, _ = _make_tree(tmp_path)
    m.set_subject_metadata(subject_dir, {"probes": {"insertions": [{"id": "a"}]}})
    m.set_subject_metadata(subject_dir, {"probes": {"note": "hi"}})   # sibling subtree
    m.set_subject_metadata(subject_dir, {"opto": {"channels": [1]}})  # different top key
    md = m.read_subject_manifest(subject_dir)["metadata"]
    assert md["probes"] == {"insertions": [{"id": "a"}], "note": "hi"}
    assert md["opto"] == {"channels": [1]}


def test_unstructured_subject_has_no_fields(tmp_path):
    subject_dir = tmp_path / "weird-subject-name"
    subject_dir.mkdir()
    m.update_subject_manifest(subject_dir, {"note": "x"})
    data = m.read_subject_manifest(subject_dir)
    assert "subject_fields" not in data
    assert data["subject"] == "weird-subject-name" and data["note"] == "x"


def test_read_absent_returns_none(tmp_path):
    subject_dir, _ = _make_tree(tmp_path)
    assert m.read_subject_manifest(subject_dir) is None
