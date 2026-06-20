"""Load a camera acquisition directory through the right backend reader.

A session container holds typed acquisitions as peers; the camera ones
(``…__video_flir``, ``…__video_rce``) are NOT behavioural sessions and are not
read by the standard session reader. This module dispatches a camera
acquisition directory to its backend's own reader and wraps the result in a
uniform :class:`CameraAcquisition`, so callers load any camera dir "through
msw" without branching on backend; the native backend object stays reachable
via ``.session``.

This is READ-ONLY: the acquisition/recording side (the msw-core camera client,
FlirBonsaiClient / RceConductorAdapter) is unaffected.

Backends are optional dependencies; the relevant package must be installed:

    video_flir -> msw_flir_bonsai     (msw[flir])
    video_rce  -> rpi_camera_ensemble (msw[rce])
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from murineshiftwork.namespace.paths import parse_acquisition_basename

log = logging.getLogger(__name__)

# acq_type prefix -> backend key
_BACKENDS = {"video_flir": "flir", "video_rce": "rce"}

# RCE per-agent core slots that define a complete capture. Mirrors
# rpi_camera_ensemble's core agent slots; used only to derive a uniform
# is_complete. Deeper QC lives in rpi_camera_ensemble.io.validate.
_RCE_CORE_SLOTS = ("ttl_out", "ttl_in", "video_h264")


@dataclass
class CameraAcquisition:
    """Uniform read result for a camera acquisition directory.

    Attributes:
        directory: The acquisition directory that was read.
        backend: ``"flir"`` or ``"rce"``.
        session: The native backend object (``FlirSession`` or ``RCESession``);
            use it for backend-specific data access.
        is_complete: Discovery-level completeness (all expected per-camera
            artifacts present). For deeper RCE QC see
            ``rpi_camera_ensemble.io.validate``.
    """

    directory: Path
    backend: str
    session: Any
    is_complete: bool


def detect_camera_backend(directory: str | Path) -> str | None:
    """Return ``"flir"``/``"rce"`` for a camera acquisition dir, else ``None``.

    Resolves the backend from the acquisition basename's ``acq_type``
    (``video_flir`` / ``video_rce``).
    """
    name = Path(directory).name
    try:
        acq_type = parse_acquisition_basename(name).get("acq_type") or ""
    except Exception:  # noqa: BLE001 - unparseable name is simply "not a camera dir"
        return None
    for prefix, backend in _BACKENDS.items():
        if acq_type.startswith(prefix):
            return backend
    return None


def _rce_is_complete(session: Any) -> bool:
    """All discovered RCE agents have their core slots present (>= 1 agent)."""
    agents = getattr(session, "agents", {}) or {}
    if not agents:
        return False
    return all(
        getattr(getattr(agent, slot), "is_present", False)
        for agent in agents.values()
        for slot in _RCE_CORE_SLOTS
    )


def load_camera_acquisition(directory: str | Path) -> CameraAcquisition:
    """Load a camera acquisition directory via its backend reader.

    Args:
        directory: A ``…__video_flir`` or ``…__video_rce`` acquisition dir.

    Returns:
        A :class:`CameraAcquisition` wrapping the native backend session.

    Raises:
        NotADirectoryError: if ``directory`` does not exist or is not a dir.
        ValueError: if the directory's ``acq_type`` is not a known camera
            backend.
        ImportError: if the backend package is not installed (the message names
            the extra to install).
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise NotADirectoryError(f"not a directory: {directory}")

    backend = detect_camera_backend(directory)

    if backend == "flir":
        try:
            from msw_flir_bonsai.readers import load_session as flir_load_session
        except ImportError as e:
            raise ImportError(
                "video_flir acquisition needs msw-flir-bonsai (pip install 'msw[flir]')"
            ) from e
        session = flir_load_session(directory)
        return CameraAcquisition(
            directory=directory,
            backend="flir",
            session=session,
            is_complete=bool(session.is_complete),
        )

    if backend == "rce":
        try:
            from rpi_camera_ensemble.readers import load_session as rce_load_session
        except ImportError as e:
            raise ImportError(
                "video_rce acquisition needs rpi-camera-ensemble "
                "(pip install 'msw[rce]')"
            ) from e
        session = rce_load_session(directory)
        return CameraAcquisition(
            directory=directory,
            backend="rce",
            session=session,
            is_complete=_rce_is_complete(session),
        )

    raise ValueError(
        f"not a recognised camera acquisition "
        f"(acq_type is not video_flir/video_rce): {directory.name}"
    )
