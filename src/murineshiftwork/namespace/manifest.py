"""Session and acquisition manifest writers.

Manifests are YAML files written progressively during a session, aligned with
the namespace hierarchy (subject > session > acquisition > file):

  session_manifest.yaml     : in the session container; lists acquisitions
  acquisition_manifest.yaml : in the acquisition dir; lists subprotocols (opto)

All write operations are atomic (write temp file, rename). Each manifest is
stamped with ``msw_namespace_version`` (the current spec semver) so a directory
can be identified without relying on its name surviving intact.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _namespace_version() -> str:
    """Return the current namespace spec semver (e.g. ``"4.2"``)."""
    from murineshiftwork.namespace.paths import get_msw_builder

    return get_msw_builder().spec.version


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def _write_yaml(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".yaml.tmp")
    with tmp.open("w") as f:
        yaml.dump(
            data, f, default_flow_style=False, allow_unicode=True, sort_keys=False
        )
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Session manifest: lives in the session container; lists acquisitions.


def init_session_manifest(session_container: str | Path, session_name: str) -> None:
    """Create session_manifest.yaml in the session container if absent."""
    p = Path(session_container) / "session_manifest.yaml"
    if p.exists():
        return
    _write_yaml(
        p,
        {
            "msw_manifest_version": 1,
            "msw_namespace_version": _namespace_version(),
            "type": "session",
            "session_name": session_name,
            "acquisitions": [],
        },
    )


def append_acquisition_to_session(
    session_container: str | Path,
    acquisition_basename: str,
    started_at: str | None = None,
) -> None:
    """Add an acquisition entry (status=running). Call at TaskProcess init."""
    p = Path(session_container) / "session_manifest.yaml"
    data: dict[str, Any] = (
        _read_yaml(p)
        if p.exists()
        else {
            "msw_manifest_version": 1,
            "msw_namespace_version": _namespace_version(),
            "type": "session",
            "acquisitions": [],
        }
    )
    acquisitions = data.setdefault("acquisitions", [])
    if not any(a.get("basename") == acquisition_basename for a in acquisitions):
        acquisitions.append(
            {
                "basename": acquisition_basename,
                "started_at": started_at or _now_iso(),
                "ended_at": None,
                "status": "running",
            }
        )
    _write_yaml(p, data)


def finalize_acquisition_in_session(
    session_container: str | Path,
    acquisition_basename: str,
    status: str = "complete",
    ended_at: str | None = None,
) -> None:
    """Set status and ended_at on an acquisition entry. Call at TaskProcess exit."""
    p = Path(session_container) / "session_manifest.yaml"
    if not p.exists():
        return
    data = _read_yaml(p)
    for a in data.get("acquisitions", []):
        if a.get("basename") == acquisition_basename:
            a["status"] = status
            a["ended_at"] = ended_at or _now_iso()
            break
    _write_yaml(p, data)


# ---------------------------------------------------------------------------
# Acquisition manifest: lives in the acquisition dir; lists subprotocols.


def init_acquisition_manifest(
    acquisition_folder: str | Path,
    acquisition_name: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Create acquisition_manifest.yaml in the acquisition dir if absent.

    Args:
        acquisition_folder: Acquisition directory.
        acquisition_name: Acquisition basename.
        metadata: Optional open provenance block written under ``metadata``
            (e.g. ``{"source": "legacy_matlab", "legacy_subject": "..."}``).
    """
    p = Path(acquisition_folder) / "acquisition_manifest.yaml"
    if p.exists():
        return
    data: dict[str, Any] = {
        "msw_manifest_version": 1,
        "msw_namespace_version": _namespace_version(),
        "type": "acquisition",
        "acquisition_name": acquisition_name,
        "subprotocols": [],
    }
    if metadata:
        data["metadata"] = dict(metadata)
    _write_yaml(p, data)


def set_manifest_metadata(manifest_path: str | Path, metadata: dict[str, Any]) -> None:
    """Merge a metadata block into an existing manifest (creates the key if absent).

    Use to stamp provenance (namespace vars, ``source`` flag, legacy ids) onto
    a session_manifest.yaml or acquisition_manifest.yaml after creation.
    """
    p = Path(manifest_path)
    data = _read_yaml(p) if p.exists() else {}
    raw = data.get("metadata")
    existing = raw if isinstance(raw, dict) else {}
    data["metadata"] = {**existing, **metadata}
    _write_yaml(p, data)


def write_acquisition_manifest_for_ingest(
    acquisition_folder: str | Path,
    acquisition_name: str,
    *,
    metadata: dict[str, Any] | None = None,
    subprotocols: list[dict[str, Any]] | None = None,
) -> Path:
    """Create a current-format acquisition manifest for externally-ingested data.

    Public entry point for an out-of-suite ingest tool that transforms older
    data (e.g. legacy MATLAB sessions) into the MSW namespace: pair the
    transformed ``.msw.df.jsonl`` with the manifest this writes, and the
    standard readers will load it via the manifest-led path. Pass ``metadata``
    with at least ``{"source": "legacy_matlab", ...}`` plus any legacy subject
    ids; the readers surface it as ``MswSession.metadata``.

    Overwrites any existing acquisition_manifest.yaml in the folder.

    Returns:
        The path to the written manifest.
    """
    p = Path(acquisition_folder) / "acquisition_manifest.yaml"
    data: dict[str, Any] = {
        "msw_manifest_version": 1,
        "msw_namespace_version": _namespace_version(),
        "type": "acquisition",
        "acquisition_name": acquisition_name,
        "subprotocols": list(subprotocols) if subprotocols else [],
    }
    if metadata:
        data["metadata"] = dict(metadata)
    _write_yaml(p, data)
    return p


def append_subprotocol(
    acquisition_folder: str | Path,
    name: str,
    filename: str,
    barcode_start: int | None = None,
) -> None:
    """Add a subprotocol entry (status=running). Call before each opto protocol."""
    p = Path(acquisition_folder) / "acquisition_manifest.yaml"
    data: dict[str, Any] = (
        _read_yaml(p)
        if p.exists()
        else {
            "msw_manifest_version": 1,
            "msw_namespace_version": _namespace_version(),
            "type": "acquisition",
            "subprotocols": [],
        }
    )
    protos = data.setdefault("subprotocols", [])
    if not any(sp.get("name") == name for sp in protos):
        protos.append(
            {
                "name": name,
                "file": filename,
                "barcode_start": barcode_start,
                "barcode_end": None,
                "status": "running",
            }
        )
    _write_yaml(p, data)


def finalize_subprotocol(
    acquisition_folder: str | Path,
    name: str,
    barcode_end: int | None = None,
    status: str = "complete",
) -> None:
    """Set barcode_end and status. Call in finally block after each opto protocol."""
    p = Path(acquisition_folder) / "acquisition_manifest.yaml"
    if not p.exists():
        return
    data = _read_yaml(p)
    for sp in data.get("subprotocols", []):
        if sp.get("name") == name:
            sp["barcode_end"] = barcode_end
            sp["status"] = status
            break
    _write_yaml(p, data)


# ---------------------------------------------------------------------------
# Subject manifest: a general key-value YAML in the subject dir (basepath/{subject})
# for records that persist across sessions. This module stays domain-agnostic: it
# provides init + a generic key extender + metadata merge + read. Specific schemas
# (e.g. probe insertions) belong in their own addon packages, which add their keys
# via update_subject_manifest() rather than baking assumptions in here.


SUBJECT_MANIFEST_NAME = "subject_manifest.yaml"


def subject_manifest_path(basepath: str | Path, subject: str) -> Path:
    """Return the subject manifest path: ``{basepath}/{subject}/subject_manifest.yaml``."""
    return Path(basepath) / subject / SUBJECT_MANIFEST_NAME


def subject_dir_for(path: str | Path) -> Path | None:
    """Resolve the subject directory (``basepath/{subject}``) from any session,
    acquisition, or file path beneath it, or from the subject dir itself.

    Returns None if a subject cannot be identified.
    """
    from murineshiftwork.namespace.paths import (
        parse_acquisition_basename,
        parse_subject,
    )

    p = Path(path)
    # From a session/acquisition/file path: parse the subject off the nearest
    # parseable basename, then return the ancestor dir named exactly that subject.
    for anc in (p, *p.parents):
        try:
            subject = parse_acquisition_basename(anc.name)["subject"]
        except Exception:
            continue
        for a2 in (anc, *anc.parents):
            if a2.name == subject:
                return a2
    # Fallback: the path is itself the subject dir (its name is a valid subject,
    # or it already holds a subject_manifest.yaml).
    if (p / SUBJECT_MANIFEST_NAME).exists():
        return p
    try:
        parse_subject(p.name)
        return p
    except Exception:
        return None


def _subject_fields(subject: str) -> dict | None:
    """Structured subject fields (subject_id/animal_id/tag_id) or None if unstructured."""
    from murineshiftwork.namespace.paths import parse_subject

    try:
        parsed = parse_subject(subject)
    except Exception:
        return None
    return {
        "subject_id": parsed["subject_id"],
        "animal_id": parsed["animal_id"],
        "tag_id": parsed["tag_id"],
    }


def _new_subject_manifest(subject: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        "msw_manifest_version": 1,
        "msw_namespace_version": _namespace_version(),
        "type": "subject",
        "subject": subject,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    fields = _subject_fields(subject)
    if fields:
        data["subject_fields"] = fields
    return data


def _load_or_init_subject(subject_dir: str | Path, subject: str | None = None) -> tuple[Path, dict]:
    p = Path(subject_dir) / SUBJECT_MANIFEST_NAME
    if p.exists():
        return p, _read_yaml(p)
    return p, _new_subject_manifest(subject or Path(subject_dir).name)


def init_subject_manifest(subject_dir: str | Path, subject: str) -> Path:
    """Create subject_manifest.yaml in the subject dir if absent. Returns its path."""
    p = Path(subject_dir) / SUBJECT_MANIFEST_NAME
    if not p.exists():
        _write_yaml(p, _new_subject_manifest(subject))
    return p


def update_subject_manifest(
    subject_dir: str | Path,
    updates: dict[str, Any],
    *,
    subject: str | None = None,
) -> None:
    """Merge arbitrary top-level keys into the subject manifest (creating it if absent).

    The general extension point. This module makes no assumptions about the shape of
    subject-level data: callers (e.g. a probe-insertion addon) own their own keys and
    pass them here. A value replaces any existing key of the same name, so do
    read -> modify -> update to accumulate into a list or nested dict.
    """
    p, data = _load_or_init_subject(subject_dir, subject)
    data.update(updates)
    data["updated_at"] = _now_iso()
    _write_yaml(p, data)


def set_subject_metadata(subject_dir: str | Path, metadata: dict[str, Any]) -> None:
    """Merge a metadata block into the subject manifest (creating it if absent)."""
    p, data = _load_or_init_subject(subject_dir)
    raw = data.get("metadata")
    existing = raw if isinstance(raw, dict) else {}
    data["metadata"] = {**existing, **metadata}
    data["updated_at"] = _now_iso()
    _write_yaml(p, data)


def read_subject_manifest(subject_dir_or_path: str | Path) -> dict | None:
    """Read the subject manifest resolved from any path beneath the subject dir.

    Returns the parsed manifest, or None if there is none.
    """
    sd = subject_dir_for(subject_dir_or_path)
    if sd is None:
        return None
    p = sd / SUBJECT_MANIFEST_NAME
    return _read_yaml(p) if p.exists() else None
