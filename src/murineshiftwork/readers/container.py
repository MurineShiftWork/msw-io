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

from murineshiftwork.namespace.manifest import (
    ACQUISITION_STATUSES,
    ACQUISITION_STATUSES_ENDED_OK,
)
from murineshiftwork.namespace.paths import parse_acquisition_basename
from murineshiftwork.readers.camera import (
    _BACKENDS,
    load_camera_acquisition,
)
from murineshiftwork.readers.namespace import test_is_recognized_msw_file

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
        status: Manifest status (one of
            :data:`~murineshiftwork.namespace.manifest.ACQUISITION_STATUSES`
            when written by MSW), or ``None``.
        is_complete: Per-acquisition completeness; ``None`` until computed by
            :func:`validate_session_container` (or if it cannot be determined,
            e.g. a camera backend package is not installed).
        remote: The manifest entry has ``location: remote`` (recorded on another
            host, e.g. an Open Ephys recording); it has no local directory.
    """

    basename: str
    acq_type: str
    kind: str
    backend: str | None
    on_disk: bool
    in_manifest: bool
    status: str | None = None
    is_complete: bool | None = None
    remote: bool = False


@dataclass
class SessionContainerReport:
    """Reconciliation of a container's acquisitions vs its manifest."""

    container: Path
    acquisitions: list[AcquisitionInfo] = field(default_factory=list)
    on_disk_not_in_manifest: list[str] = field(default_factory=list)
    in_manifest_not_on_disk: list[str] = field(default_factory=list)
    status_issues: list[str] = field(default_factory=list)
    remote: list[str] = field(default_factory=list)

    @property
    def is_consistent(self) -> bool:
        """True when disk and manifest agree on the set of acquisitions."""
        return not self.on_disk_not_in_manifest and not self.in_manifest_not_on_disk


def _has_recognized_files(directory: Path) -> bool:
    """True if the dir holds any recognised MSW file (current or legacy)."""
    try:
        return any(
            test_is_recognized_msw_file(f) for f in directory.iterdir() if f.is_file()
        )
    except (PermissionError, OSError):
        return False


def _classify(acq_type: str, path: Path | None) -> tuple[str, str | None]:
    """Map an acquisition to (kind, backend).

    Primary signal is the parsed ``acq_type`` (namespace validation). A dir that
    does not parse but holds recognised MSW files is a legacy behavioural
    acquisition (still readable); only a dir that neither parses nor holds
    recognised files is ``unknown``.
    """
    for prefix, backend in _BACKENDS.items():
        if acq_type.startswith(prefix):
            return "camera", backend
    if acq_type:
        return "behaviour", None
    if path is not None and _has_recognized_files(path):
        return "behaviour", None
    return "unknown", None


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
    """basename -> dir for every acquisition-looking child directory on disk.

    A child counts if its name uses the ``__`` namespace separator OR it holds
    recognised MSW files (current or legacy). The content check keeps legacy
    acquisitions whose names predate the ``__`` convention discoverable.
    """
    return {
        d.name: d
        for d in sorted(container.iterdir())
        if d.is_dir() and ("__" in d.name or _has_recognized_files(d))
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
        kind, backend = _classify(acq_type, disk.get(basename))
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
                remote=entry.get("location") == "remote",
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


def _status_issue(info: AcquisitionInfo, running_is_issue: bool) -> str | None:
    """Describe a manifest status that needs attention, or None."""
    status = info.status
    if status is None or status in ACQUISITION_STATUSES_ENDED_OK:
        return None
    if status == "running":
        return f"{info.basename}: status 'running'" if running_is_issue else None
    if status in ACQUISITION_STATUSES:
        return f"{info.basename}: ended with status '{status}'"
    return f"{info.basename}: unknown status '{status}'"


def validate_session_container(
    container: str | Path, running_is_issue: bool = False
) -> SessionContainerReport:
    """Reconcile a container's on-disk acquisitions against its manifest.

    Enumerates acquisitions, computes per-acquisition completeness, and reports
    disk/manifest mismatches: acquisitions present on disk but unregistered
    (e.g. an old manifest predating camera registration), and acquisitions
    listed in the manifest but missing on disk (a dangling or aborted capture).
    Manifest statuses other than a normal end (``complete``/``stopped``) go to
    ``status_issues``; ``running`` only when ``running_is_issue`` is set, since a
    live session is legitimately running. Entries with ``location: remote`` live
    on another host: they go to ``remote``, not ``in_manifest_not_on_disk``.

    Args:
        container: The session container directory.
        running_is_issue: Report entries still ``running`` as issues.

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
            i.basename
            for i in infos
            if i.in_manifest and not i.on_disk and not i.remote
        ],
        remote=[i.basename for i in infos if i.remote],
        status_issues=[
            msg for i in infos if (msg := _status_issue(i, running_is_issue))
        ],
    )
