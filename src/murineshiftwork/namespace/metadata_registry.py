"""Optional, non-fatal validation of manifest ``metadata`` subtrees.

Core stays a generic deep-merge key-tree (``manifest.py``); addon packages own the
schema for their own subtree and advertise a ``MetadataProtocol`` via the
``msw.metadata`` entry-point group. This registry discovers those addons and offers
warn-and-degrade validation of a surfaced ``metadata`` dict.

Design invariants (mirroring ``validate_task_yaml``):
- **Never raises.** A missing addon, a broken entry point, or an invalid subtree
  yields warnings, not an exception - ``metadata`` is optional and legacy/partial
  trees must still load.
- **Pass-through by default.** Subtrees with no registered addon are ignored (not an
  error), so an environment without an addon still reads the raw subtree.

Discovery is lazy + cached; an addon is only needed when a consumer opts into
validation. If ``msw-plugin-api`` is absent, the registry degrades to duck-typing.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

ENTRY_POINT_GROUP = "msw.metadata"

try:  # msw-plugin-api is a light, zero-dep contract package; degrade if absent.
    from msw_plugin_api import MetadataProtocol

    def _is_addon(obj: object) -> bool:
        return isinstance(obj, MetadataProtocol)
except Exception:  # pragma: no cover - only when plugin-api is not installed

    def _is_addon(obj: object) -> bool:
        return (
            isinstance(getattr(obj, "subtree", None), str)
            and hasattr(obj, "schema_version")
            and callable(getattr(obj, "validate", None))
        )


_ADDONS: dict[str, Any] | None = None  # subtree -> addon instance (cached)


def _discover() -> dict[str, Any]:
    """Load ``msw.metadata`` entry points into a ``{subtree: addon}`` map (cached).

    Failure-isolated: a broken or non-conforming entry point is skipped, never fatal.
    """
    global _ADDONS
    if _ADDONS is not None:
        return _ADDONS
    addons: dict[str, Any] = {}
    try:
        eps = entry_points(group=ENTRY_POINT_GROUP)
    except Exception:
        eps = []
    for ep in eps:
        try:
            obj = ep.load()
            addon = obj() if isinstance(obj, type) else obj
        except Exception:
            continue
        if _is_addon(addon):
            addons[addon.subtree] = addon
    _ADDONS = addons
    return addons


def reset_cache() -> None:
    """Clear the discovery cache (for tests / after installing an addon)."""
    global _ADDONS
    _ADDONS = None


def registered_subtrees() -> list[str]:
    """Return the metadata subtrees for which an addon is registered."""
    return sorted(_discover())


def validate_metadata(metadata: dict | None) -> dict[str, list[str]]:
    """Validate each registered subtree of a surfaced ``metadata`` dict.

    Args:
        metadata: A manifest metadata dict (e.g. ``MswSession.metadata``) or None.

    Returns:
        ``{subtree: [warnings]}`` for every registered subtree present in
        ``metadata`` that produced at least one warning. Empty when everything is
        valid or nothing is registered/present. Subtrees with no registered addon
        are ignored. Never raises.
    """
    if not metadata:
        return {}
    addons = _discover()
    result: dict[str, list[str]] = {}
    for subtree, addon in addons.items():
        if subtree not in metadata:
            continue
        try:
            warnings = addon.validate(metadata[subtree])
        except Exception as exc:  # an addon that raises is itself a warning, not fatal
            warnings = [f"metadata.{subtree}: validator raised {exc!r}"]
        if warnings:
            result[subtree] = list(warnings)
    return result
