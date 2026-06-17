"""MswSession: structured result of reading a single MSW session directory."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003  # pydantic validates Path fields at runtime
from typing import Any

import pandas as pd  # noqa: TC002  # pydantic validates pd.DataFrame at runtime
from pydantic import BaseModel, ConfigDict


class MswSession(BaseModel):
    """All data and metadata for one MSW session directory.

    Attributes:
        session_dir: Absolute path to the session directory.
        basename: Session basename (``subject__datetime__task``).
        subject: Animal identifier extracted from the basename.
        datetime_str: Raw datetime string extracted from the basename.
        task: Task name extracted from the basename.
        namespace_version: Namespace version string (``"v1"`` or ``"legacy"``),
            or ``None`` if the directory name is not a canonical basename.
        artifact_format: One of ``"session_yaml"``, ``"separate_json"``,
            or ``"legacy"``.
        msw_version: MSW software version recorded in ``settings.process``,
            or ``"legacy"`` / ``"< 1.0.0"`` for older sessions.
        df: Trial-by-trial DataFrame, or ``None`` if no trial data file
            was found.
        settings_task: Task settings dict (``settings.task`` artifact).
        settings_process: Process settings dict (``settings.process`` artifact).
        settings_stage: Stage / reward settings dict, if present.
        settings_ephys: Host-session / ephys linking block, if present.
        subprotocols: List of subprotocol dicts from ``session_manifest.yaml``,
            populated for multi-protocol sessions.
        is_complete: ``True`` when the required artifacts (df, settings.task,
            settings.process) are all present and non-null.
        is_ephys: ``True`` when an ephys/host-session block is present.
        acquisition_name: Name of the parent acquisition container, set by
            ``load_acquisition``; ``None`` for standalone sessions.
        acquisition_dir: Path to the parent acquisition container, set by
            ``load_acquisition``; ``None`` for standalone sessions.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # identity
    session_dir: Path
    basename: str
    subject: str
    datetime_str: str
    task: str
    acq_type: str = ""

    # provenance
    namespace_version: str | None
    artifact_format: str
    msw_version: str

    # content
    df: pd.DataFrame | None = None
    settings_task: dict[str, Any] | None = None
    settings_process: dict[str, Any] | None = None
    settings_stage: dict[str, Any] | None = None
    settings_ephys: dict[str, Any] | None = None

    # multi-protocol metadata (populated when session_manifest.yaml is present)
    subprotocols: list[dict] | None = None

    # flags
    is_complete: bool
    is_ephys: bool

    # acquisition context: set by load_acquisition(), absent for standalone sessions
    acquisition_name: str | None = None
    acquisition_dir: Path | None = None

    @property
    def host_session_name(self) -> str | None:
        """Name of the host/ephys session container, or None if standalone."""
        if self.settings_ephys is None:
            return None
        return self.settings_ephys.get("session_name")

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_dir": str(self.session_dir),
            "basename": self.basename,
            "subject": self.subject,
            "datetime_str": self.datetime_str,
            "task": self.task,
            "acq_type": self.acq_type,
            "namespace_version": self.namespace_version,
            "artifact_format": self.artifact_format,
            "msw_version": self.msw_version,
            "df": self.df,
            "settings_task": self.settings_task,
            "settings_process": self.settings_process,
            "settings_stage": self.settings_stage,
            "settings_ephys": self.settings_ephys,
            "subprotocols": self.subprotocols,
            "is_complete": self.is_complete,
            "is_ephys": self.is_ephys,
            "acquisition_name": self.acquisition_name,
            "acquisition_dir": str(self.acquisition_dir)
            if self.acquisition_dir
            else None,
        }
