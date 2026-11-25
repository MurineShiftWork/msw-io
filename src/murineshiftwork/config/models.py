"""Config document models (schema version 3).

A document has four sections, each a collection keyed by name:

- ``machines``: the entities plugged into one host (``devices``, and ``boxes`` as
  attached devices with valves and their calibrations), plus host facts (``os``,
  ``paths``, ``services``) and machine-level ``settings``.
- ``setups``: the machine a setup belongs to and the entities it uses, as a map from
  role (``bpod``, ``box``, ``sound``, ``cameras``, ...) to an entity name on that
  machine.
- ``tasks``: the roles a task requires, its site settings and named ``modes``.
- ``subjects``: identity, settings, and per-task ``state`` written after sessions.

Entities are facts and are typed; settings are a free-form nested mapping with one
rule (shared keys plain, task keys under ``tasks.<task>``). Unknown keys are refused
everywhere except where hardware types differ (devices, box ports) and in identity,
so a typo in a config fails instead of being ignored.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Final, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

SCHEMA_VERSION: Final = 3
"""The config schema version this package reads and writes."""

SECTIONS = ("machines", "setups", "tasks", "subjects")
"""Top-level document sections, in the order a config tree is loaded."""


def _check_settings(value: dict[str, Any]) -> dict[str, Any]:
    tasks = value.get("tasks")
    if tasks is None:
        return value
    if not isinstance(tasks, dict) or not all(
        isinstance(v, dict) for v in tasks.values()
    ):
        raise ValueError("settings.tasks must map task names to mappings")
    return value


Settings = Annotated[
    dict[str, Any],
    BeforeValidator(lambda v: {} if v is None else v),
    AfterValidator(_check_settings),
]
"""Free-form settings: shared keys plain, task keys under ``tasks.<task>``; null is empty."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SecretRef(_Strict):
    """A secret referenced by name; the value is filled in on the executing host."""

    secret: str


class Device(BaseModel):
    """A device on a machine, identified by ``type``.

    Fields beyond ``type`` and the port depend on the device type and are kept as
    given (``model_extra``). A ``port`` names the device directly (``COM1``);
    ``port_by_path`` names a stable bus path that the executing host turns into a
    device node.
    """

    model_config = ConfigDict(extra="allow")

    type: str
    port: str | None = None
    port_by_path: str | None = None


class Calibration(_Strict):
    """Valve calibration: ``points`` are ``(open time in s, volume in uL)`` pairs."""

    updated: datetime | date | None = None
    points: list[tuple[float, float]] = Field(default_factory=list)


class Valve(_Strict):
    """One valve of a box; without a calibration it cannot deliver a set volume."""

    calibration: Calibration | None = None


class Port(BaseModel):
    """One port of a box; fields other than ``water`` depend on the hardware."""

    model_config = ConfigDict(extra="allow")

    water: bool = False


class Box(_Strict):
    """A box attached to a machine: ports, valves with calibrations, lick sensors."""

    ports: dict[int, Port] = Field(default_factory=dict)
    valves: dict[int, Valve] = Field(default_factory=dict)
    lick_sensors: dict[str, str] = Field(default_factory=dict)


class Machine(_Strict):
    """One host and its entities. Device and box names share one namespace."""

    os: str | None = None
    paths: dict[str, str] = Field(default_factory=dict)
    services: dict[str, dict[str, Any]] = Field(default_factory=dict)
    devices: dict[str, Device] = Field(default_factory=dict)
    boxes: dict[str, Box] = Field(default_factory=dict)
    settings: Settings = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_entity_names(self) -> Machine:
        both = sorted(set(self.devices) & set(self.boxes))
        if both:
            raise ValueError(f"names used for both a device and a box: {both}")
        return self


class Setup(_Strict):
    """A setup: the machine it belongs to and the entity it uses for each role."""

    machine: str
    uses: dict[str, str] = Field(default_factory=dict)
    settings: Settings = Field(default_factory=dict)


class Task(_Strict):
    """Site settings for a task: required roles, settings and named modes.

    A mode is a settings block applied on top of the task's settings when the run
    selects it; it stays at the task level, so subject settings still win over it.
    """

    requires: list[str] = Field(default_factory=list)
    settings: Settings = Field(default_factory=dict)
    modes: dict[str, Settings] = Field(default_factory=dict)


class Identity(BaseModel):
    """Who a subject is; fields beyond these are kept as given."""

    model_config = ConfigDict(extra="allow")

    registered: datetime | date | None = None
    project: str | None = None
    experiment: str | None = None
    aliases: list[str] = Field(default_factory=list)


class Subject(_Strict):
    """A subject: identity, settings, and ``state`` per task (machine-written)."""

    identity: Identity = Field(default_factory=Identity)
    settings: Settings = Field(default_factory=dict)
    state: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ConfigDocument(_Strict):
    """The merged config: every file is a fragment of one document of this shape."""

    schema_version: Literal[3] = SCHEMA_VERSION
    machines: dict[str, Machine] = Field(default_factory=dict)
    setups: dict[str, Setup] = Field(default_factory=dict)
    tasks: dict[str, Task] = Field(default_factory=dict)
    subjects: dict[str, Subject] = Field(default_factory=dict)
