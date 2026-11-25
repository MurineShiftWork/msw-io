"""Deep merge of nested mappings with per-leaf provenance.

Mappings merge by key path and the later value wins. Anything that is not a mapping
(scalars, lists, ``None``) is a leaf and replaces the earlier value whole: lists are
never concatenated. An empty mapping merged onto a mapping changes nothing; where
nothing was before, it is a leaf and records where it came from.

Provenance is a flat dict from key path (a tuple of string keys) to an opaque label.
When a value replaces a subtree, every recorded path below it is dropped first, so the
provenance always describes exactly the leaves of the merged result.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from datetime import date, datetime, time
from typing import Any, TypeVar

KeyPath = tuple[str, ...]
L = TypeVar("L")


def to_jsonable(value: Any) -> Any:
    """Return ``value`` as JSON-native data: string keys, ISO dates, lists for tuples.

    Applied to every fragment before merging, so key paths, provenance and the
    resolved payload use the same spelling as the payload after a JSON round trip
    (a YAML key ``4`` and the JSON key ``"4"`` are the same path).

    Raises:
        TypeError: for a value with no JSON form (a set, an object).
    """
    if isinstance(value, Mapping):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(v) for v in value]
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if value is None or isinstance(value, str | bool | int | float):
        return value
    raise TypeError(f"config value of type {type(value).__name__} has no JSON form")


def iter_leaves(value: Any, path: KeyPath = ()) -> Iterator[tuple[KeyPath, Any]]:
    """Yield ``(key path, value)`` for every leaf of a nested mapping."""
    if isinstance(value, Mapping) and value:
        for k, v in value.items():
            yield from iter_leaves(v, (*path, str(k)))
    else:
        yield path, value


def deep_merge(
    dst: dict[str, Any],
    src: Mapping[str, Any],
    provenance: dict[KeyPath, L],
    label: L | Callable[[KeyPath], L],
    path: KeyPath = (),
) -> None:
    """Merge ``src`` into ``dst`` in place and record ``label`` for each leaf written.

    Args:
        dst: merged result so far; mutated.
        src: mapping merged on top; never mutated (subtrees are copied).
        provenance: key path to label for every leaf of ``dst``; mutated.
        label: the label of ``src``, or a function from a leaf's full key path to its
            label when the leaves of ``src`` come from different places.
        path: key path of ``dst`` inside the document the provenance describes.
    """
    for k, v in src.items():
        key = str(k)
        p = (*path, key)
        if isinstance(v, Mapping) and isinstance(dst.get(key), dict):
            if not v:
                continue
            if not dst[key]:
                provenance.pop(p, None)
            deep_merge(dst[key], v, provenance, label, p)
            continue
        if key in dst:
            _drop_below(provenance, p)
        dst[key] = _copy(v)
        for leaf, _ in iter_leaves(v, p):
            provenance[leaf] = label(leaf) if callable(label) else label


def _copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy(v) for v in value]
    return value


def _drop_below(provenance: dict[KeyPath, Any], prefix: KeyPath) -> None:
    n = len(prefix)
    for key in [key for key in provenance if key[:n] == prefix]:
        del provenance[key]


def get_path(value: Mapping[str, Any], path: KeyPath) -> Any:
    """Return the value at ``path``, or ``None`` when any key on the way is missing."""
    cur: Any = value
    for key in path:
        if not isinstance(cur, Mapping) or key not in cur:
            return None
        cur = cur[key]
    return cur


def to_pointer(path: KeyPath) -> str:
    """Return the JSON pointer (RFC 6901) for a key path: ``("a", "b/c")`` is ``/a/b~1c``."""
    return "".join("/" + k.replace("~", "~0").replace("/", "~1") for k in path)


def from_pointer(pointer: str) -> KeyPath:
    """Return the key path of a JSON pointer; the inverse of :func:`to_pointer`."""
    if not pointer:
        return ()
    if not pointer.startswith("/"):
        raise ValueError(f"not a JSON pointer: {pointer!r}")
    return tuple(
        k.replace("~1", "/").replace("~0", "~") for k in pointer[1:].split("/")
    )
