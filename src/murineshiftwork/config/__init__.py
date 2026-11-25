"""Config model v3: document models, fragment loader, and the run resolver.

Typical use::

    from murineshiftwork.config import load_config, resolve

    config = load_config("path/to/config", revision="<commit>")
    run = resolve(config, setup="a", subject="m1", task="sequence")
    payload = run.to_json()  # send to the executing host
    same = ResolvedRun.from_json(payload)  # checks the content hash

Nothing here touches hardware or reads secret values; binding a run to a host is a
separate step on the executing side.
"""

from murineshiftwork.config.errors import (
    ConfigError,
    ContentHashError,
    RequirementError,
    SchemaVersionError,
    UnknownNameError,
    UnresolvedReferenceError,
)
from murineshiftwork.config.loader import (
    LoadedConfig,
    check_fragment,
    load_config,
    merge_fragments,
    tree_files,
)
from murineshiftwork.config.models import (
    SCHEMA_VERSION,
    SECTIONS,
    Box,
    Calibration,
    ConfigDocument,
    Device,
    Identity,
    Machine,
    Port,
    SecretRef,
    Settings,
    Setup,
    Subject,
    Task,
    Valve,
)
from murineshiftwork.config.resolve import (
    FILE_REFERENCES,
    ReferenceLoader,
    file_reference_loader,
    find_secrets,
    resolve,
    scope_settings,
)
from murineshiftwork.config.run import (
    LEVELS,
    Level,
    ResolvedMachine,
    ResolvedRun,
    Source,
    canonical_json,
)

__all__ = [
    "FILE_REFERENCES",
    "LEVELS",
    "SCHEMA_VERSION",
    "SECTIONS",
    "Box",
    "Calibration",
    "ConfigDocument",
    "ConfigError",
    "ContentHashError",
    "Device",
    "Identity",
    "Level",
    "LoadedConfig",
    "Machine",
    "Port",
    "ReferenceLoader",
    "RequirementError",
    "ResolvedMachine",
    "ResolvedRun",
    "SchemaVersionError",
    "SecretRef",
    "Settings",
    "Setup",
    "Source",
    "Subject",
    "Task",
    "UnknownNameError",
    "UnresolvedReferenceError",
    "Valve",
    "canonical_json",
    "check_fragment",
    "file_reference_loader",
    "find_secrets",
    "load_config",
    "merge_fragments",
    "resolve",
    "scope_settings",
    "tree_files",
]
