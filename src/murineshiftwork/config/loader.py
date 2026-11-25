"""Load config fragments into one document, with the source file of every value.

A config tree is a directory whose files are fragments of one document. They are
read in a fixed order (``machines/``, ``setups/``, ``tasks/``, ``subjects/``, each
sorted by name, then the extra files in the order given) and merged by key path,
the last file winning. Any file may hold any section; the directories only fix the
order.

Every fragment must declare ``schema_version: 3`` at the top. A file without it, or
with another version, is refused before anything is merged, so a tree never mixes
versions.

Source labels are paths relative to the config root, so two checkouts of the same
revision in different places give the same provenance. A file outside the root is
labelled by its name only: its location is a fact of the host, not of the config.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from murineshiftwork.config.errors import ConfigError, SchemaVersionError
from murineshiftwork.config.merge import KeyPath, deep_merge, to_jsonable
from murineshiftwork.config.models import SCHEMA_VERSION, SECTIONS, ConfigDocument

FRAGMENT_SUFFIXES = (".yaml", ".yml")


@dataclass
class LoadedConfig:
    """A merged config document together with where each value came from.

    Attributes:
        document: the validated document.
        sources: source label (file relative to ``root``) for every leaf of the
            merged document, by key path; keys are strings (a YAML key ``1`` is
            ``"1"``) and include the section (``("setups", "a", "machine")``).
        root: config root; referenced files (camera configs) are read relative to
            it. ``None`` for fragments that did not come from a directory.
        revision: source revision of the config (a commit, a tag, a content id),
            as given by the caller; never derived here.
        files: source labels in the order they were merged.
    """

    document: ConfigDocument
    sources: dict[KeyPath, str] = field(default_factory=dict)
    root: Path | None = None
    revision: str | None = None
    files: list[str] = field(default_factory=list)


def check_fragment(fragment: Any, label: str) -> dict[str, Any]:
    """Return a fragment's sections after checking its schema version and keys.

    Raises:
        SchemaVersionError: when ``schema_version`` is missing or not 3.
        ConfigError: when the fragment is not a mapping or has an unknown
            top-level key.
    """
    if fragment is None:
        fragment = {}
    if not isinstance(fragment, Mapping):
        raise ConfigError(f"{label}: a config file must be a mapping")
    version = fragment.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SchemaVersionError(
            f"{label}: schema_version is {version!r}, this loader reads "
            f"{SCHEMA_VERSION} only; migrate the config before loading it"
        )
    body = {k: v for k, v in fragment.items() if k != "schema_version"}
    unknown = sorted(str(k) for k in body if k not in SECTIONS)
    if unknown:
        raise ConfigError(
            f"{label}: unknown top-level keys {unknown}; allowed: {list(SECTIONS)}"
        )
    return body


def merge_fragments(
    fragments: Iterable[tuple[str, Any]],
    *,
    root: Path | None = None,
    revision: str | None = None,
) -> LoadedConfig:
    """Merge already-parsed fragments in order, the last one winning per key path.

    Args:
        fragments: ``(source label, parsed fragment)`` pairs, lowest priority first.
        root: config root recorded on the result, for inlining referenced files.
        revision: source revision recorded on the result.

    Raises:
        SchemaVersionError: when any fragment is not schema version 3; nothing is
            merged in that case.
        ConfigError: for a fragment that is not a mapping or has unknown sections.
        pydantic.ValidationError: when the merged document does not validate.
    """
    checked = [(label, check_fragment(frag, label)) for label, frag in fragments]
    raw: dict[str, Any] = {}
    sources: dict[KeyPath, str] = {}
    for label, body in checked:
        deep_merge(raw, to_jsonable(body), sources, label)
    document = ConfigDocument.model_validate(raw)
    return LoadedConfig(
        document=document,
        sources=sources,
        root=root,
        revision=revision,
        files=[label for label, _ in checked],
    )


def tree_files(root: Path) -> list[Path]:
    """Return the fragment files of a config tree in load order."""
    files: list[Path] = []
    for section in SECTIONS:
        directory = root / section
        if directory.is_dir():
            files += sorted(
                p
                for p in directory.iterdir()
                if p.is_file() and p.suffix in FRAGMENT_SUFFIXES
            )
    return files


def source_label(path: Path, root: Path) -> str:
    """Return the provenance label of a file: relative to ``root``, else its name."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def load_config(
    root: str | Path,
    extra_files: Sequence[str | Path] = (),
    *,
    revision: str | None = None,
) -> LoadedConfig:
    """Load a config tree and extra files into one document.

    Args:
        root: config root holding ``machines/``, ``setups/``, ``tasks/`` and
            ``subjects/``; a missing section directory is skipped.
        extra_files: files merged after the tree, in order (a host-only fragment,
            per-run override files).
        revision: source revision to record; the loader never inspects version
            control itself.

    Raises:
        SchemaVersionError: when any file is not schema version 3.
        ConfigError: for a file that is not a mapping or has unknown sections.
        FileNotFoundError: when an extra file does not exist.
        pydantic.ValidationError: when the merged document does not validate.
    """
    root = Path(root)
    paths = [*tree_files(root), *(Path(p) for p in extra_files)]
    fragments = []
    for path in paths:
        with path.open(encoding="utf-8") as fh:
            fragments.append((source_label(path, root), yaml.safe_load(fh)))
    return merge_fragments(fragments, root=root, revision=revision)
