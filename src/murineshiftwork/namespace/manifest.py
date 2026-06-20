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
