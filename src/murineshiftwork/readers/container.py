"""Enumerate and validate the acquisitions in a session container.

A session container holds one or more typed acquisitions as peers (a
behavioural acquisition, and optionally camera acquisitions such as
``video_flir`` / ``video_rce``). The ``session_manifest.yaml`` lists them, but
the manifest may be **incomplete or absent** - old sessions predate camera
registration, and a crash can leave an acquisition unregistered.

This module treats the **disk as the source of truth** and the manifest as a
metadata/status overlay:

- :func:`enumerate_acquisitions` returns every acquisition found by unioning the
  on-disk directories with the manifest entries, each flagged with whether it is
  on disk and/or in the manifest.
- :func:`validate_session_container` reconciles the two and reports per-
  acquisition completeness plus any disk/manifest mismatch, so an incomplete old
  manifest is surfaced rather than silently trusted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from murineshiftwork.namespace.paths import parse_acquisition_basename
from murineshiftwork.readers.camera import (
    _BACKENDS,
    load_camera_acquisition,
)

log = logging.getLogger(__name__)

_MANIFEST_NAMES = ("session_manifest.yaml", "acquisition_manifest.yaml")


@dataclass
class AcquisitionInfo:
    """One acquisition in a container, reconciled against the manifest.

    Attributes:
        basename: Acquisition directory name.
        acq_type: Parsed acq_type (e.g. ``sequence``, ``video_flir``); ``""`` if
            the name does not parse as an acquisition basename.
        kind: ``"behaviour"``, ``"camera"``, or ``"unknown"``.
        backend: Camera backend (``"flir"``/``"rce"``) when ``kind == "camera"``.
        on_disk: The directory exists in the container.
        in_manifest: The manifest lists this acquisition.
        status: Manifest status (``running``/``complete``/...), or ``None``.
        is_complete: Per-acquisition completeness; ``None`` until computed by
            :func:`validate_session_container` (or if it cannot be determined,
            e.g. a camera backend package is not installed).
    """

    basename: str
    acq_type: str
    kind: str
    backend: str | None
    on_disk: bool
    in_manifest: bool
    status: str | None = None
    is_complete: bool | None = None


@dataclass
class SessionContainerReport:
    """Reconciliation of a container's acquisitions vs its manifest."""

    container: Path
    acquisitions: list[AcquisitionInfo] = field(default_factory=list)
    on_disk_not_in_manifest: list[str] = field(default_factory=list)
    in_manifest_not_on_disk: list[str] = field(default_factory=list)

    @property
    def is_consistent(self) -> bool:
        """True when disk and manifest agree on the set of acquisitions."""
        return not self.on_disk_not_in_manifest and not self.in_manifest_not_on_disk


def _classify(acq_type: str) -> tuple[str, str | None]:
    """Map an acq_type to (kind, backend)."""
    for prefix, backend in _BACKENDS.items():
        if acq_type.startswith(prefix):
            return "camera", backend
    return ("behaviour", None) if acq_type else ("unknown", None)


def _acq_type_of(basename: str) -> str:
    try:
        return parse_acquisition_basename(basename).get("acq_type") or ""
    except Exception:  # noqa: BLE001 - unparseable name -> not a typed acquisition
        return ""


def _manifest_index(container: Path) -> dict[str, dict]:
    """basename -> manifest entry, from the first manifest found (or empty)."""
    for name in _MANIFEST_NAMES:
        p = container / name
        if not p.exists():
            continue
        data = yaml.safe_load(p.read_text()) or {}
        entries = data.get("acquisitions") or data.get("sessions") or []
        out: dict[str, dict] = {}
        for e in entries:
            bn = e.get("basename") or e.get("session_dir")
            if bn:
                out[bn] = e
        return out
    return {}


def _disk_acquisition_dirs(container: Path) -> dict[str, Path]:
    """basename -> dir for every ``__``-separated child directory on disk."""
    return {
        d.name: d for d in sorted(container.iterdir()) if d.is_dir() and "__" in d.name
    }


def enumerate_acquisitions(container: str | Path) -> list[AcquisitionInfo]:
    """List every acquisition in a container (disk union manifest).

    Args:
        container: The session container directory.

    Returns:
        One :class:`AcquisitionInfo` per acquisition, sorted by basename. Cheap:
        does not open or load any acquisition (``is_complete`` is left ``None``).
    """
    container = Path(container)
    disk = _disk_acquisition_dirs(container)
    manifest = _manifest_index(container)

    infos: list[AcquisitionInfo] = []
    for basename in sorted(set(disk) | set(manifest)):
        acq_type = _acq_type_of(basename)
        kind, backend = _classify(acq_type)
        entry = manifest.get(basename) or {}
        infos.append(
            AcquisitionInfo(
                basename=basename,
                acq_type=acq_type,
                kind=kind,
                backend=backend,
                on_disk=basename in disk,
                in_manifest=basename in manifest,
                status=entry.get("status"),
            )
        )
    return infos


def _completeness(container: Path, info: AcquisitionInfo) -> bool | None:
    """Best-effort per-acquisition completeness (None if undeterminable)."""
    if not info.on_disk:
        return None
    path = container / info.basename
    try:
        if info.kind == "camera":
            return load_camera_acquisition(path).is_complete
        if info.kind == "behaviour":
            from murineshiftwork.readers.batch import load_session

            return load_session(path).is_complete
    except Exception as e:  # noqa: BLE001 - missing backend / unreadable -> unknown
        log.debug("completeness undetermined for %s: %s", info.basename, e)
    return None


def validate_session_container(container: str | Path) -> SessionContainerReport:
    """Reconcile a container's on-disk acquisitions against its manifest.

    Enumerates acquisitions, computes per-acquisition completeness, and reports
    disk/manifest mismatches: acquisitions present on disk but unregistered
    (e.g. an old manifest predating camera registration), and acquisitions
    listed in the manifest but missing on disk (a dangling or aborted capture).

    Args:
        container: The session container directory.

    Returns:
        A :class:`SessionContainerReport`.
    """
    container = Path(container)
    infos = enumerate_acquisitions(container)
    for info in infos:
        info.is_complete = _completeness(container, info)
    return SessionContainerReport(
        container=container,
        acquisitions=infos,
        on_disk_not_in_manifest=[
            i.basename for i in infos if i.on_disk and not i.in_manifest
        ],
        in_manifest_not_on_disk=[
            i.basename for i in infos if i.in_manifest and not i.on_disk
        ],
    )
