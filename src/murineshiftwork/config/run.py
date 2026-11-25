"""The resolved run: a self-contained payload that one host resolves and another runs.

A ``ResolvedRun`` holds everything the executing host needs and nothing it has to look
up in the config: the selected entities with referenced files inlined, the settings of
the running task, the subject's state for that task, and provenance for every value.
Host-specific work (device nodes from ``port_by_path``, secret values, local paths)
happens after it, on the host that executes the run.

It is plain JSON data. ``content_hash`` is the sha256 of the canonical JSON of the
payload without ``content_hash`` and ``revision``, so the same config content gives the
same hash wherever and from whichever checkout it was resolved, and a receiver can
check that the payload arrived unchanged.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from murineshiftwork.config.errors import ContentHashError, SchemaVersionError
from murineshiftwork.config.models import SCHEMA_VERSION, Box, Device, Identity

Level = Literal["defaults", "machine", "setup", "task", "mode", "subject", "run"]
"""Config levels, lowest priority first."""

LEVELS: tuple[Level, ...] = (
    "defaults",
    "machine",
    "setup",
    "task",
    "mode",
    "subject",
    "run",
)

HASH_EXCLUDE = frozenset({"content_hash", "revision"})


def canonical_json(value: Any) -> str:
    """Return the canonical JSON text of ``value``: sorted keys, no whitespace, UTF-8.

    Raises:
        ValueError: for NaN or infinite floats, which have no JSON form.
    """
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_hex(value: Any) -> str:
    """Return the sha256 hex digest of the canonical JSON of ``value``."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(_Strict):
    """Where a value came from: its level and the file (relative to the config root).

    ``file`` is ``None`` for values that did not come from a file: package defaults
    and run overrides passed in memory.
    """

    level: Level
    file: str | None = None


class ResolvedMachine(_Strict):
    """The machine the run's setup belongs to, without its entity collections."""

    name: str
    os: str | None = None
    paths: dict[str, str] = Field(default_factory=dict)
    services: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ResolvedRun(_Strict):
    """One resolved run, ready to be sent to the host that executes it.

    Attributes:
        schema_version: config schema version the run was resolved from.
        machine: the setup's machine (host facts and services).
        setup, subject, task, mode: what was resolved.
        requires: roles the task requires; all present in ``uses``.
        uses: role to entity name, as the setup selects them.
        devices: the selected devices, by name; file references inlined as
            ``{"file", "content_sha256", "content"}``.
        boxes: the selected boxes, by name.
        settings: resolved settings; shared keys plain, the running task's keys
            under ``tasks.<task>`` (no other task's block).
        state: the subject's state for the running task.
        identity: the subject's identity.
        secrets: JSON pointer (into this payload) to secret name for every
            ``{secret: name}`` reference; values are never resolved here.
        provenance: JSON pointer (into this payload) to the level and file of
            each value that came from config.
        revision: source revision of the config, when the caller supplied one.
        content_hash: sha256 of the canonical JSON of the payload without
            ``content_hash`` and ``revision``.
    """

    schema_version: Literal[3] = SCHEMA_VERSION
    machine: ResolvedMachine
    setup: str
    subject: str
    task: str
    mode: str | None = None
    requires: list[str] = Field(default_factory=list)
    uses: dict[str, str] = Field(default_factory=dict)
    devices: dict[str, Device] = Field(default_factory=dict)
    boxes: dict[str, Box] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)
    state: dict[str, Any] = Field(default_factory=dict)
    identity: Identity = Field(default_factory=Identity)
    secrets: dict[str, str] = Field(default_factory=dict)
    provenance: dict[str, Source] = Field(default_factory=dict)
    revision: str | None = None
    content_hash: str = ""

    def compute_hash(self) -> str:
        """Return the content hash of this payload as it is now."""
        return sha256_hex(self.model_dump(mode="json", exclude=set(HASH_EXCLUDE)))

    def with_hash(self) -> ResolvedRun:
        """Return a copy whose ``content_hash`` matches its payload."""
        return self.model_copy(update={"content_hash": self.compute_hash()})

    def verify(self) -> None:
        """Check that ``content_hash`` matches the payload.

        Raises:
            ContentHashError: when it does not.
        """
        actual = self.compute_hash()
        if self.content_hash != actual:
            raise ContentHashError(
                f"content hash mismatch: payload says {self.content_hash!r}, "
                f"content gives {actual!r}"
            )

    def to_json(self, *, indent: int | None = None) -> str:
        """Return the run as JSON text."""
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_json(cls, text: str | bytes, *, verify: bool = True) -> ResolvedRun:
        """Parse a run from JSON text, by default checking its content hash.

        Raises:
            SchemaVersionError: when the payload is not schema version 3.
            ContentHashError: when ``verify`` is true and the hash does not match.
            pydantic.ValidationError: when the payload does not validate.
        """
        data = json.loads(text)
        if isinstance(data, dict) and data.get("schema_version") != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"resolved run has schema_version {data.get('schema_version')!r}, "
                f"this reader reads {SCHEMA_VERSION} only"
            )
        run = cls.model_validate(data)
        if verify:
            run.verify()
        return run
