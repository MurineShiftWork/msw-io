"""Resolve a run (setup, subject, task, mode) from a config document.

Resolution is pure apart from the optional reference hook: it reads no host state
and no environment, so the same document gives the same ``ResolvedRun`` on any host.

Order of work:

1. Select the setup, its machine and the task (a task without a site entry
   resolves from package defaults alone) and the subject.
2. Check that the setup provides every role the task requires, before anything
   else is built, and map each role through ``uses`` to a machine entity.
3. Inline the files that selected devices reference (``FILE_REFERENCES``), so the
   payload carries no file references.
4. Merge settings by level: package defaults < machine < setup < task < mode <
   subject < run. At every level only the running task's ``tasks.<task>`` block
   is kept (shared keys plain, task keys under the task's name), so one task's
   settings never reach another. A ``null`` at a level inherits the value below.
5. Collect secret names, record provenance, and hash the payload.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from murineshiftwork.config.errors import (
    RequirementError,
    UnknownNameError,
    UnresolvedReferenceError,
)
from murineshiftwork.config.loader import LoadedConfig
from murineshiftwork.config.merge import (
    KeyPath,
    deep_merge,
    iter_leaves,
    to_jsonable,
    to_pointer,
)
from murineshiftwork.config.models import ConfigDocument, Task
from murineshiftwork.config.run import (
    Level,
    ResolvedMachine,
    ResolvedRun,
    RunSource,
    Source,
    sha256_hex,
)

ReferenceLoader = Callable[[str], Any]
"""Hook that returns the parsed content of a file referenced from the config."""

FILE_REFERENCES: Mapping[str, tuple[str, ...]] = {"cameras": ("config",)}
"""Device fields that hold a file reference, by device type."""


def file_reference_loader(root: str | Path) -> ReferenceLoader:
    """Return a hook that reads referenced YAML or JSON files below ``root``.

    The hook refuses absolute references and references that leave ``root``, so a
    config can only inline files of its own tree.
    """
    base = Path(root).resolve()

    def load(reference: str) -> Any:
        rel = PurePosixPath(reference)
        if rel.is_absolute() or ".." in rel.parts:
            raise UnresolvedReferenceError(
                f"file reference {reference!r} must be relative to the config root"
            )
        path = base.joinpath(*rel.parts)
        if not path.is_file():
            raise UnresolvedReferenceError(f"referenced file {reference!r} not found")
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    return load


def scope_settings(settings: Mapping[str, Any] | None, task: str) -> dict[str, Any]:
    """Return settings with only the running task's ``tasks.<task>`` block kept."""
    out = {k: v for k, v in (settings or {}).items() if k != "tasks"}
    block = ((settings or {}).get("tasks") or {}).get(task)
    if block is not None:
        out["tasks"] = {task: block}
    return out


def resolve(
    document: ConfigDocument | LoadedConfig,
    setup: str,
    subject: str,
    task: str,
    mode: str | None = None,
    run_overrides: Mapping[str, Any] | None = None,
    package_defaults: Mapping[str, Any] | None = None,
    *,
    package_versions: Mapping[str, str] | None = None,
    run_id: str | None = None,
    source: RunSource | None = None,
    load_reference: ReferenceLoader | None = None,
    file_references: Mapping[str, tuple[str, ...]] = FILE_REFERENCES,
) -> ResolvedRun:
    """Resolve one run into a self-contained, hashed payload.

    Args:
        document: the config, either as loaded (with sources, root and source)
            or as a bare document (provenance then has levels but no files).
        setup: setup name; selects the machine and the entities.
        subject: subject name.
        task: task name. A task with no entry in the document has no required
            roles and no site settings.
        mode: a mode of the task, applied at the task level.
        run_overrides: settings for this run only, the highest level; the same
            shape as any level's settings.
        package_defaults: the task package's own settings, the lowest level.
        package_versions: distribution name to version of the packages that
            supplied ``package_defaults``, recorded in the payload.
        run_id: identifier to record for this run; none is generated, so
            resolution stays deterministic.
        source: where the config came from; defaults to the loaded config's.
        load_reference: hook that inlines referenced files; defaults to reading
            below the loaded config's root.
        file_references: device fields that hold a file reference, by type.

    Raises:
        UnknownNameError: for an undefined setup, machine, subject, mode or
            entity named in ``uses``.
        RequirementError: when the setup does not provide a role the task
            requires.
        UnresolvedReferenceError: when a referenced file cannot be inlined.
    """
    if isinstance(document, LoadedConfig):
        loaded = document
        doc = loaded.document
        sources = loaded.sources
        source = source or loaded.source
        if load_reference is None and loaded.root is not None:
            load_reference = file_reference_loader(loaded.root)
    else:
        doc, sources = document, {}

    setup_cfg = _pick(doc.setups, setup, "setup")
    machine_name = setup_cfg.machine
    machine_cfg = _pick(doc.machines, machine_name, f"machine (of setup {setup!r})")
    subject_cfg = _pick(doc.subjects, subject, "subject")
    task_cfg = doc.tasks.get(task, Task())

    missing = [role for role in task_cfg.requires if role not in setup_cfg.uses]
    if missing:
        raise RequirementError(
            f"task {task!r} requires roles {missing} that setup {setup!r} does not "
            f"provide (it provides {sorted(setup_cfg.uses)})"
        )
    if mode is not None and mode not in task_cfg.modes:
        raise UnknownNameError(
            f"task {task!r} has no mode {mode!r} (modes: {sorted(task_cfg.modes)})"
        )

    provenance: dict[KeyPath, Source] = {}

    def copy_sources(
        doc_prefix: KeyPath, payload_prefix: KeyPath, level: Level
    ) -> None:
        n = len(doc_prefix)
        for key, label in sources.items():
            if key[:n] == doc_prefix:
                provenance[payload_prefix + key[n:]] = Source(level=level, file=label)

    m_path: KeyPath = ("machines", machine_name)
    devices: dict[str, Any] = {}
    boxes: dict[str, Any] = {}
    for role, name in setup_cfg.uses.items():
        if name in machine_cfg.devices:
            if name not in devices:
                copy_sources((*m_path, "devices", name), ("devices", name), "machine")
                devices[name] = _inline_device(
                    name,
                    machine_cfg.devices[name].model_dump(mode="json"),
                    load_reference,
                    file_references,
                    provenance,
                )
        elif name in machine_cfg.boxes:
            copy_sources((*m_path, "boxes", name), ("boxes", name), "machine")
            boxes[name] = machine_cfg.boxes[name]
        else:
            raise UnknownNameError(
                f"setup {setup!r} uses {name!r} as {role!r}, but machine "
                f"{machine_name!r} has no device or box of that name"
            )

    for key in ("os", "paths", "services"):
        copy_sources((*m_path, key), ("machine", key), "machine")
    copy_sources(("setups", setup, "uses"), ("uses",), "setup")
    copy_sources(("tasks", task, "requires"), ("requires",), "task")
    copy_sources(("subjects", subject, "identity"), ("identity",), "subject")
    copy_sources(("subjects", subject, "state", task), ("state",), "subject")

    levels: list[tuple[Level, Mapping[str, Any] | None, KeyPath | None]] = [
        ("defaults", package_defaults, None),
        ("machine", machine_cfg.settings, (*m_path, "settings")),
        ("setup", setup_cfg.settings, ("setups", setup, "settings")),
        ("task", task_cfg.settings, ("tasks", task, "settings")),
    ]
    if mode is not None:
        levels.append(("mode", task_cfg.modes[mode], ("tasks", task, "modes", mode)))
    levels += [
        ("subject", subject_cfg.settings, ("subjects", subject, "settings")),
        ("run", run_overrides, None),
    ]

    settings: dict[str, Any] = {}
    settings_prov: dict[KeyPath, Source] = {}
    for level, block, doc_prefix in levels:
        scoped = to_jsonable(scope_settings(block, task))
        label = _labeller(level, doc_prefix, sources)
        deep_merge(settings, scoped, settings_prov, label, none_inherits=True)
    settings.setdefault("tasks", {}).setdefault(task, {})
    for key, src in settings_prov.items():
        provenance[("settings", *key)] = src

    run = ResolvedRun(
        machine=ResolvedMachine(
            name=machine_name,
            os=machine_cfg.os,
            paths=machine_cfg.paths,
            services=to_jsonable(machine_cfg.services),
        ),
        setup=setup,
        subject=subject,
        task=task,
        mode=mode,
        requires=list(task_cfg.requires),
        uses=dict(setup_cfg.uses),
        devices=devices,
        boxes=boxes,
        settings=settings,
        state=to_jsonable(subject_cfg.state.get(task, {})),
        identity=subject_cfg.identity,
        provenance={to_pointer(k): v for k, v in sorted(provenance.items())},
        packages=dict(package_versions or {}),
        run_id=run_id,
        source=source or RunSource(),
    )
    payload = run.model_dump(mode="json", exclude={"provenance", "secrets"})
    run = run.model_copy(update={"secrets": find_secrets(payload)})
    return run.with_hash()


def find_secrets(payload: Any) -> dict[str, str]:
    """Return JSON pointer to secret name for every ``{secret: name}`` in ``payload``."""
    found: dict[str, str] = {}

    def walk(value: Any, path: KeyPath) -> None:
        if isinstance(value, dict):
            if set(value) == {"secret"} and isinstance(value["secret"], str):
                found[to_pointer(path)] = value["secret"]
                return
            for k, v in value.items():
                walk(v, (*path, str(k)))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, (*path, str(i)))

    walk(payload, ())
    return dict(sorted(found.items()))


def _pick(collection: Mapping[str, Any], name: str, what: str) -> Any:
    if name not in collection:
        raise UnknownNameError(
            f"unknown {what} {name!r} (defined: {sorted(collection)})"
        )
    return collection[name]


def _labeller(
    level: Level, doc_prefix: KeyPath | None, sources: Mapping[KeyPath, str]
) -> Callable[[KeyPath], Source]:
    def label(leaf: KeyPath) -> Source:
        file = None if doc_prefix is None else sources.get(doc_prefix + leaf)
        return Source(level=level, file=file)

    return label


def _inline_device(
    name: str,
    spec: dict[str, Any],
    load_reference: ReferenceLoader | None,
    file_references: Mapping[str, tuple[str, ...]],
    provenance: dict[KeyPath, Source],
) -> dict[str, Any]:
    for field in file_references.get(spec.get("type", ""), ()):
        reference = spec.get(field)
        if not isinstance(reference, str):
            continue
        if load_reference is None:
            raise UnresolvedReferenceError(
                f"device {name!r} references {reference!r} in {field!r}, and no "
                "reference loader is available to inline it"
            )
        content = to_jsonable(load_reference(reference))
        spec[field] = {
            "file": reference,
            "content_sha256": sha256_hex(content),
            "content": content,
        }
        prefix = ("devices", name, field)
        written_in = provenance.pop(prefix, Source(level="machine"))
        provenance[(*prefix, "file")] = written_in
        from_file = Source(level="machine", file=reference)
        provenance[(*prefix, "content_sha256")] = from_file
        for leaf, _ in iter_leaves(content, (*prefix, "content")):
            provenance[leaf] = from_file
    return spec
