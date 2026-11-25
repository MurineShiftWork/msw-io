"""Exceptions raised while loading and resolving a config document."""

from __future__ import annotations


class ConfigError(ValueError):
    """Base class for config loading and resolution errors."""


class SchemaVersionError(ConfigError):
    """A config file or payload declares a schema version this loader does not read."""


class UnknownNameError(ConfigError):
    """A run names a setup, machine, task, subject, mode or entity that is not defined."""


class RequirementError(ConfigError):
    """The setup does not provide every role the task requires."""


class UnresolvedReferenceError(ConfigError):
    """An entity references a file that could not be inlined into the resolved run."""


class ContentHashError(ConfigError):
    """A resolved run's content hash does not match its payload."""
