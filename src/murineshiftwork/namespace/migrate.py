"""In-place migration of MSW data trees to the current namespace shape.

Shapes handled, oldest first (``{dt}`` is the datetime token):

    legacy 3-component behaviour : {sub}__{dt}__{task}          -> {sub}__{dt}__msw__{task}
    v4 __vN behaviour            : {sub}__{dt}__{task}__vN       -> {sub}__{dt}__msw__{task}
    v4 __vN, msw already present : {sub}__{dt}__msw__{task}__vN  -> {sub}__{dt}__msw__{task}
    typed acq with __vN          : {sub}__{dt}__video_flir__vN   -> {sub}__{dt}__video_flir
    v3 session container         : {sub}__{dt}__session_{task}   -> {sub}__{dt}
    non-underscored test task    : {sub}__{dt}__msw__test_x      -> {sub}__{dt}__msw___test_x
    legacy optotagging subdirs   : flattened to peer ``video_rce`` acquisitions

Mechanism: :func:`run` walks ``data_root/<subject>/<container>/<acquisition>``.
Targets come from :func:`parse_acquisition_basename` and the namespace builder
with the version omitted, so ``__vN`` is dropped and recorded as
``metadata.task_version`` in the acquisition manifest. A directory whose target
equals its name is left alone, which makes a second ``apply`` run a no-op.

For each migrated acquisition, :class:`Migrator` renames the directory and every
file (recursively) whose name starts with ``<old basename>.``, rewrites the old
basename inside ``.yaml``/``.yml``/``.json`` files, and updates or creates the
``acquisition_manifest.yaml`` and the parent ``session_manifest.yaml``.

Critical choices:

- Dry run is the default; nothing is written unless ``apply`` is set.
- A target that already exists is a collision. It is classified DUPLICATE when
  both trees have the same relative file list and sizes, CONFLICT otherwise.
  Only file names and sizes are compared, never contents, so large binaries are
  not read. Data is removed only for ``on_conflict="delete"`` on a DUPLICATE;
  a CONFLICT in delete mode is quarantined instead, so differing data is never
  lost.
- Test subjects and acquisitions (leading ``_``) are skipped unless
  ``include_test``; the audit scans them anyway, since a test task without the
  leading ``_`` is exactly what it must catch.
- Optotagging parents (named ``..__optotagging`` with no direct files) cannot be
  renamed flat. Without ``flatten_optotagging`` they are reported as skipped,
  never silently ignored.
"""

from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from murineshiftwork.namespace.paths import (
    _KNOWN_ACQ_TYPES,
    get_msw_builder,
    parse_acquisition_basename,
)

QUARANTINE_DIRNAME = "_migration_quarantine"
_TEXT_SUFFIXES = {".yaml", ".yml", ".json"}
SHAPES = ("legacy3comp", "vN", "typed", "all")
LEVELS = ("acquisition", "container", "all")
ON_CONFLICT = ("skip", "quarantine", "delete")

# v3 session container: {subject}__{dt}__session_{task}
_SESSION_TASK_RE = re.compile(
    r"^(?P<subject>[^_][\w\-]*)__(?P<dt>\d{8}_\d{6}(?:_\d{6})?)__session_(?P<task>.+)$"
)
# session_type = the token after `{subject}__{datetime}` on a (non-v3) container.
_SESSION_TYPE_RE = re.compile(r"^.+?__\d{8}_\d{6}(?:_\d{6})?__(?P<st>[\w\-]+)$")
# Test/calibration tasks must be `_`-prefixed so they are filtered out of the main
# datasets; a non-underscored one gets a target that differs from its name.
_TEST_TASK_RE = re.compile(r"^(test|calibration)_")
# A camera sidecar file: {prefix}.rce.rpi-<id>.<YYYYMMDDHHMMSS>.<suffix>
_RCE_FILE_RE = re.compile(r"\.rce\.rpi-[\w\-]+\.(?P<ts>\d{14})\.")
_DATETIME_HEAD_RE = re.compile(r"^\d{8}_\d{6}")


class DataRootError(ValueError):
    """The data root is missing or does not look like an MSW subject tree."""


def _normalize_task(task: str | None) -> str | None:
    """Prepend a leading '_' to a non-underscored test/calibration task token."""
    return "_" + task if task and _TEST_TASK_RE.match(task) else task


def target_acq_basename(old_name: str) -> tuple[str | None, dict] | None:
    """Return ``(target, info)`` for an acquisition name, or None if unparseable.

    ``target`` is None when the name is already current.
    """
    try:
        info = parse_acquisition_basename(old_name)
    except ValueError:
        return None
    values = {
        "subject": info["subject"],
        "datetime": info["datetime_str"],
        "acq_type": info["acq_type"],
    }
    if info["task"]:
        values["task"] = _normalize_task(info["task"])
    target = get_msw_builder().build_path("acquisition", values)
    return (None, info) if target == old_name else (target, info)


def _shape(info: dict) -> str:
    if info["acq_version"] is not None:
        return "vN"
    if info["is_legacy_acquisition"]:
        return "legacy3comp"
    return "typed"


def check_data_root(data_root: Path) -> None:
    """Raise :class:`DataRootError` unless ``data_root`` holds subject dirs.

    A subject dir is a child ``S`` holding a container named ``S__<datetime>...``.
    This catches a subject or session dir passed by mistake: there the children's
    names do not continue with a datetime.
    """
    if not data_root.is_dir():
        raise DataRootError(f"{data_root} is not a directory")
    for sub in data_root.iterdir():
        if not sub.is_dir() or sub.name == QUARANTINE_DIRNAME:
            continue
        prefix = sub.name + "__"
        for c in sub.iterdir():
            if (
                c.is_dir()
                and c.name.startswith(prefix)
                and _DATETIME_HEAD_RE.match(c.name[len(prefix) :])
            ):
                return
    raise DataRootError(
        f"{data_root} has no subject dirs (<subject>/<subject>__<datetime>...): "
        "pass the data root that holds the subject folders"
    )


# ---------------------------------------------------------------------------
# collision handling (metadata only; never hashes big binaries)


def _inventory(root: Path) -> dict[str, int]:
    inv: dict[str, int] = {}
    for p in root.rglob("*"):
        if p.is_file() and not p.is_symlink():
            try:
                inv[p.relative_to(root).as_posix()] = p.stat().st_size
            except OSError:
                inv[p.relative_to(root).as_posix()] = -1
    return inv


def _quarantine_dest(src: Path, root: Path) -> Path:
    dest = root / src.parent.name / src.name
    n = 1
    while dest.exists():  # never clobber a prior quarantined dir
        dest = root / src.parent.name / f"{src.name}__dup{n}"
        n += 1
    return dest


# ---------------------------------------------------------------------------
# yaml helpers


def _load_yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _dump_yaml(p: Path, data: dict, apply: bool) -> None:
    if not apply:
        return
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        yaml.dump(
            data, f, default_flow_style=False, allow_unicode=True, sort_keys=False
        )
    tmp.replace(p)


def _replace_in_obj(obj: Any, old: str, new: str) -> Any:
    """Recursively replace ``old`` with ``new`` in all string values."""
    if isinstance(obj, str):
        return obj.replace(old, new)
    if isinstance(obj, list):
        return [_replace_in_obj(x, old, new) for x in obj]
    if isinstance(obj, dict):
        return {k: _replace_in_obj(v, old, new) for k, v in obj.items()}
    return obj


def _looks_like_acquisition(d: Path) -> bool:
    if (d / "acquisition_manifest.yaml").exists():
        return True
    return any(
        ".msw." in p.name or p.name.count("__") >= 2 for p in d.iterdir() if p.is_file()
    )


def _optotagging_children(parent: Path) -> list[tuple[Path, str]] | None:
    """Return ``[(child_dir, subprotocol), ...]`` for a legacy optotagging parent.

    Detection: the name parses with ``task == 'optotagging'``, the dir holds no
    direct files, and every child dir name extends the parent's with
    ``__{subprotocol}``. Anything else returns None and is left untouched.
    """
    res = target_acq_basename(parent.name)
    info = res[1] if res is not None else None
    if info is None or info["task"] != "optotagging":
        return None
    if any(p.is_file() for p in parent.iterdir()):
        return None
    children = []
    prefix = parent.name + "__"
    for child in sorted(d for d in parent.iterdir() if d.is_dir()):
        if not child.name.startswith(prefix):
            return None
        children.append((child, child.name[len(prefix) :]))
    return children or None


def _optotagging_target(child: Path) -> tuple[str, str] | None:
    """Return ``(target_basename, old_file_prefix)`` for one subprotocol dir.

    Note:
        The target datetime is the subprotocol's own recording second (the
        ``.rce.*.{ts}.`` token, shared across cameras and distinct per
        subprotocol), so sibling subprotocols do not collide on the parent's
        datetime. The file prefix is read from a file name rather than rebuilt,
        because legacy files use a single ``_`` where the dir uses ``__``.
    """
    subject = child.name.split("__", 1)[0]
    prefix = ts = None
    for f in sorted(child.iterdir()):
        m = _RCE_FILE_RE.search(f.name)
        if m and f.is_file():
            prefix = f.name.split(".rce.")[0]
            ts = m.group("ts")
            break
    if prefix is None or ts is None:
        return None
    target = get_msw_builder().build_path(
        "acquisition",
        {
            "subject": subject,
            "datetime": f"{ts[:8]}_{ts[8:14]}",
            "acq_type": "video_rce",
        },
    )
    return target, prefix


# ---------------------------------------------------------------------------


@dataclass
class MigrationOptions:
    """Options for :func:`run`; defaults match the CLI defaults (a dry run)."""

    apply: bool = False
    subjects: list[str] | None = None
    level: str = "acquisition"
    acq_type: str = "all"
    shape: str = "all"
    on_conflict: str = "skip"
    quarantine_dir: Path | None = None
    create_manifests: bool = True
    include_test: bool = False
    flatten_optotagging: bool = False


@dataclass
class MigrationReport:
    """What a run planned or did; ``to_dict`` is the JSON report layout.

    ``actions`` holds one entry per directory rename or flatten, ``conflicts``
    one per collision with its classification and resolution, ``skipped`` the
    directories that would need migrating but were left untouched.
    """

    data_root: str
    apply: bool
    target_spec: str
    options: dict
    actions: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)

    @property
    def migrated(self) -> int:
        return len(self.actions)

    @property
    def resolved(self) -> int:
        return sum(1 for c in self.conflicts if c["resolution"] != "skip")

    @property
    def unresolved(self) -> int:
        return sum(1 for c in self.conflicts if c["resolution"] == "skip")

    def to_dict(self) -> dict:
        return {
            "data_root": self.data_root,
            "mode": "apply" if self.apply else "dry-run",
            "target_spec": self.target_spec,
            "options": self.options,
            "summary": {
                "migrated": self.migrated,
                "conflicts_resolved": self.resolved,
                "conflicts_unresolved": self.unresolved,
                "skipped": len(self.skipped),
            },
            "actions": self.actions,
            "conflicts": self.conflicts,
            "skipped": self.skipped,
        }


def write_report(report: dict, path: Path) -> None:
    """Write a report dict as indented JSON (UTF-8), creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


class Migrator:
    """One migration pass over a data root; printing and reporting as it goes."""

    def __init__(self, data_root: Path, opts: MigrationOptions):
        self.root = data_root
        self.o = opts
        self.spec = get_msw_builder().spec.version
        self.qroot = opts.quarantine_dir or (data_root / QUARANTINE_DIRNAME)
        options = {k: v for k, v in vars(opts).items() if k != "apply"}
        options["quarantine_dir"] = str(self.qroot)
        self.report = MigrationReport(
            data_root=str(data_root),
            apply=opts.apply,
            target_spec=self.spec,
            options=options,
        )

    def _rel(self, p: Path) -> str:
        try:
            return p.relative_to(self.root).as_posix()
        except ValueError:
            return str(p)

    # -- collisions ---------------------------------------------------------

    def _resolve_conflict(self, kind_of: str, old: Path, new: Path) -> None:
        dup = _inventory(old) == _inventory(new)
        kind = "DUPLICATE" if dup else "CONFLICT"
        rel = f"{old.parent.name}/{old.name}"
        entry = {
            "kind": kind_of,
            "classification": kind,
            "path": self._rel(old),
            "target": self._rel(new),
            "applied": self.o.apply,
        }
        mode = self.o.on_conflict
        if mode == "skip":
            print(f"SKIP  ({kind}, target exists): {old.name} -> {new.name}")
            entry["resolution"] = "skip"
        elif mode == "delete" and dup:
            if self.o.apply:
                shutil.rmtree(old)
            print(
                f"{'DELETED' if self.o.apply else 'WOULD-DELETE'}  ({kind}, identical): {rel}"
            )
            entry["resolution"] = "delete"
        else:
            # quarantine mode, or delete mode falling back for a CONFLICT
            dest = _quarantine_dest(old, self.qroot)
            note = "" if dup else ", not identical: kept for review"
            if self.o.apply:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old), str(dest))
            verb = "QUARANTINED" if self.o.apply else "WOULD-QUARANTINE"
            print(f"{verb}  ({kind}{note}): {rel} -> {dest}")
            entry["resolution"] = "quarantine"
            entry["quarantine_dest"] = str(dest)
        self.report.conflicts.append(entry)

    # -- manifests ----------------------------------------------------------

    def _ensure_acq_manifest(
        self, acq_dir: Path, old_bn: str, target: str, task_version: int | None
    ) -> list[str]:
        p = acq_dir / "acquisition_manifest.yaml"
        spec = self.spec
        changes: list[str] = []
        if p.exists():
            data = _replace_in_obj(_load_yaml(p), old_bn, target)
            data["acquisition_name"] = target
            data["msw_namespace_version"] = spec
        elif self.o.create_manifests:
            data = {
                "msw_manifest_version": 1,
                "msw_namespace_version": spec,
                "type": "acquisition",
                "acquisition_name": target,
                "subprotocols": [],
            }
            changes.append("+ created acquisition_manifest.yaml")
        else:
            return changes
        if task_version is not None:
            md = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
            md["task_version"] = task_version
            md.setdefault("source", "namespace_migration")
            data["metadata"] = md
        if not changes:
            changes.append(
                f"acquisition_manifest: name+stamp -> {target} "
                f"(v{spec}, task_version={task_version})"
            )
        _dump_yaml(p, data, self.o.apply)
        return changes

    def _ensure_session_manifest(
        self, container: Path, old_bn: str, target: str
    ) -> list[str]:
        p = container / "session_manifest.yaml"
        spec = self.spec
        changes: list[str] = []
        entry = {
            "basename": target,
            "status": "complete",
            "started_at": None,
            "ended_at": None,
        }
        if p.exists():
            data = _load_yaml(p)
            acqs = data.get("acquisitions") or []
            found = False
            for a in acqs:
                if isinstance(a, dict) and a.get("basename") == old_bn:
                    a["basename"] = target
                    found = True
            if not found:
                acqs.append(entry)
                changes.append(f"session_manifest: + acquisitions[] {target}")
            data["acquisitions"] = acqs
            if data.get("msw_namespace_version") != spec:
                changes.append(
                    f"session_manifest: version "
                    f"{data.get('msw_namespace_version')} -> {spec}"
                )
                data["msw_namespace_version"] = spec
        elif self.o.create_manifests:
            data = {
                "msw_manifest_version": 1,
                "msw_namespace_version": spec,
                "type": "session",
                "session_name": container.name,
                "acquisitions": [entry],
            }
            changes.append("+ created session_manifest.yaml")
        else:
            return changes
        _dump_yaml(p, data, self.o.apply)
        return changes

    # -- acquisitions -------------------------------------------------------

    def _passes_filters(self, info: dict) -> bool:
        if self.o.acq_type != "all" and info["acq_type"] != self.o.acq_type:
            return False
        return self.o.shape == "all" or _shape(info) == self.o.shape

    def migrate_acquisition(self, acq_dir: Path) -> None:
        """Rename one acquisition dir, its files and manifests to the target."""
        res = target_acq_basename(acq_dir.name)
        if res is None or res[0] is None:
            return
        target, info = res
        assert target is not None
        if not self._passes_filters(info):
            return

        old_bn = acq_dir.name
        new_dir = acq_dir.parent / target
        if new_dir.exists():
            self._resolve_conflict("acquisition", acq_dir, new_dir)
            return

        file_renames = sorted(
            (p, p.with_name(target + p.name[len(old_bn) :]))
            for p in acq_dir.rglob("*")
            if p.is_file() and p.name.startswith(old_bn + ".")
        )
        task_version = info["acq_version"]
        apply = self.o.apply

        print(
            f"{'MIGRATE ' if apply else 'DRY-RUN '} "
            f"{acq_dir.parent.name}/{old_bn}  [{_shape(info)}]"
        )
        print(f"    dir  {old_bn} -> {target}")
        if file_renames:
            n_text = sum(1 for o, _ in file_renames if o.suffix in _TEXT_SUFFIXES)
            print(
                f"    files  {len(file_renames)} renamed to the new basename "
                f"({n_text} with embedded-ref rewrite)"
            )
            for o, n in file_renames:
                print(f"      {o.relative_to(acq_dir).as_posix()} -> {n.name}")
        changes = self._ensure_acq_manifest(acq_dir, old_bn, target, task_version)
        changes += self._ensure_session_manifest(acq_dir.parent, old_bn, target)
        for c in changes:
            print(f"    {c}")

        if apply:
            for old_f, new_f in file_renames:
                if old_f.suffix in _TEXT_SUFFIXES:
                    text = old_f.read_text(encoding="utf-8")
                    new_f.write_text(text.replace(old_bn, target), encoding="utf-8")
                    old_f.unlink()
                else:
                    old_f.rename(new_f)
            acq_dir.rename(new_dir)

        self.report.actions.append(
            {
                "kind": "acquisition",
                "shape": _shape(info),
                "path": self._rel(acq_dir),
                "target": self._rel(new_dir),
                "task_version": task_version,
                "files": [
                    {
                        "path": o.relative_to(acq_dir).as_posix(),
                        "target": n.name,
                        "rewrite": o.suffix in _TEXT_SUFFIXES,
                    }
                    for o, n in file_renames
                ],
                "manifests": changes,
                "applied": apply,
            }
        )

    def _write_opto_acq_manifest(
        self, new_dir: Path, target: str, subprotocol: str, opto_session: str
    ) -> None:
        data = {
            "msw_manifest_version": 1,
            "msw_namespace_version": self.spec,
            "type": "acquisition",
            "acquisition_name": target,
            "subprotocols": [],
            "metadata": {
                "optotagging_subprotocol": subprotocol,
                "optotagging_session": opto_session,
                "source": "namespace_migration",
            },
        }
        _dump_yaml(new_dir / "acquisition_manifest.yaml", data, self.o.apply)

    def migrate_optotagging_parent(self, parent: Path) -> None:
        """Flatten one optotagging parent into peer ``video_rce`` acquisitions.

        Each subprotocol dir moves up into the container as
        ``{subject}__{subprotocol_dt}__video_rce``; the subprotocol name goes to
        the new acquisition manifest metadata. The parent is removed only once
        it is empty.
        """
        children = _optotagging_children(parent)
        if not children:
            return
        container = parent.parent
        apply = self.o.apply
        moved = 0

        for child, subprotocol in children:
            tgt = _optotagging_target(child)
            if tgt is None:
                print(f"    SKIP (no .rce files): {child.name}")
                self.report.skipped.append(
                    {"path": self._rel(child), "reason": "optotagging: no .rce files"}
                )
                continue
            target, old_prefix = tgt
            new_dir = container / target
            if new_dir.exists():
                self._resolve_conflict("optotagging", child, new_dir)
                continue

            files = sorted(p for p in child.iterdir() if p.is_file())
            # Text sidecar refs: the path segment first, then any residual
            # child-dir ref, then the file basename ref.
            subs = [
                (f"{parent.name}/{child.name}", target),
                (child.name, target),
                (old_prefix, target),
            ]
            renames = [
                (f, new_dir / (target + f.name[len(old_prefix) :])) for f in files
            ]

            print(
                f"{'FLATTEN ' if apply else 'DRY-RUN '} "
                f"{container.name}/{parent.name}/{child.name}"
            )
            print(
                f"    -> {container.name}/{target}  (subprotocol '{subprotocol}' -> manifest)"
            )
            print(f"    files  {len(files)} moved up + renamed")
            for f, dest in renames:
                print(f"      {f.name} -> {dest.name}")

            if apply:
                new_dir.mkdir(parents=True, exist_ok=True)
                for f, dest in renames:
                    if f.suffix in _TEXT_SUFFIXES:
                        text = f.read_text(encoding="utf-8")
                        for old, new in subs:
                            text = text.replace(old, new)
                        dest.write_text(text, encoding="utf-8")
                        f.unlink()
                    else:
                        f.rename(dest)
                self._write_opto_acq_manifest(new_dir, target, subprotocol, parent.name)
                if not any(child.iterdir()):
                    child.rmdir()
            # old basename == target: a re-run finds the entry and does not duplicate
            changes = self._ensure_session_manifest(container, target, target)
            for c in changes:
                print(f"    {c}")
            moved += 1
            self.report.actions.append(
                {
                    "kind": "optotagging",
                    "shape": "optotagging",
                    "path": self._rel(child),
                    "target": self._rel(new_dir),
                    "subprotocol": subprotocol,
                    "files": [
                        {
                            "path": f.name,
                            "target": d.name,
                            "rewrite": f.suffix in _TEXT_SUFFIXES,
                        }
                        for f, d in renames
                    ],
                    "manifests": ["+ created acquisition_manifest.yaml", *changes],
                    "applied": apply,
                }
            )

        if apply and moved and not any(parent.iterdir()):
            parent.rmdir()
            print(f"    removed empty parent {parent.name}")
        elif apply and moved:
            print(
                f"    WARNING: parent {parent.name} not empty after flatten: left in place"
            )

    def migrate_container(self, container: Path) -> None:
        """Rename a v3 ``{sub}__{dt}__session_{task}`` container to ``{sub}__{dt}``."""
        m = _SESSION_TASK_RE.match(container.name)
        if not m:
            return
        target = f"{m.group('subject')}__{m.group('dt')}"
        new_dir = container.parent / target
        if new_dir.exists():
            self._resolve_conflict("container", container, new_dir)
            return
        apply = self.o.apply
        print(
            f"{'MIGRATE ' if apply else 'DRY-RUN '} container "
            f"{container.parent.name}/{container.name} -> {target}"
        )
        sm = container / "session_manifest.yaml"
        if sm.exists() and apply:
            data = _load_yaml(sm)
            data["session_name"] = target
            _dump_yaml(sm, data, apply)
        if apply:
            container.rename(new_dir)
        self.report.actions.append(
            {
                "kind": "container",
                "shape": "v3_session",
                "path": self._rel(container),
                "target": self._rel(new_dir),
                "files": [],
                "manifests": ["session_manifest: session_name"] if sm.exists() else [],
                "applied": apply,
            }
        )

    # -- walk ---------------------------------------------------------------

    def _subject_dirs(self, include_test: bool) -> list[Path]:
        qroot = self.qroot.resolve()
        dirs = sorted(
            d
            for d in self.root.iterdir()
            if d.is_dir() and d.name != QUARANTINE_DIRNAME and d.resolve() != qroot
        )
        if self.o.subjects:
            dirs = [d for d in dirs if d.name in self.o.subjects]
        if not include_test:
            dirs = [d for d in dirs if not d.name.startswith("_")]
        return dirs

    def _visit_acquisition(self, acq: Path) -> None:
        if _looks_like_acquisition(acq):
            self.migrate_acquisition(acq)
            return
        if self.o.flatten_optotagging and _optotagging_children(acq) is not None:
            self.migrate_optotagging_parent(acq)
            return
        # The name parses as an acquisition that would migrate, but the dir holds
        # no direct files (e.g. the optotagging subdir layout). The flat renamer
        # cannot handle it; report it rather than omit it silently.
        res = target_acq_basename(acq.name)
        if res is None or res[0] is None:
            return
        if not self._passes_filters(res[1]):
            return
        self.report.skipped.append(
            {
                "path": self._rel(acq),
                "reason": "parses as an acquisition, no direct files",
            }
        )

    def run(self) -> MigrationReport:
        level = self.o.level
        for subject_dir in self._subject_dirs(self.o.include_test):
            for container in sorted(d for d in subject_dir.iterdir() if d.is_dir()):
                if level in ("acquisition", "all"):
                    for acq in sorted(d for d in container.iterdir() if d.is_dir()):
                        if not self.o.include_test and acq.name.startswith("_"):
                            continue
                        self._visit_acquisition(acq)
                if level in ("container", "all"):
                    self.migrate_container(container)
        self._print_summary()
        return self.report

    def _print_summary(self) -> None:
        r = self.report
        apply = self.o.apply
        print()
        print(
            f"{'Migrated' if apply else 'Would migrate'} {r.migrated} "
            f"director(y/ies) (target spec v{self.spec})."
        )
        if r.resolved:
            print(
                f"{'Resolved' if apply else 'Would resolve'} {r.resolved} collision(s)."
            )
        if r.unresolved:
            print(
                f"{r.unresolved} collision(s) left in place "
                f"(--on-conflict={self.o.on_conflict})."
            )
        if r.skipped:
            print()
            print(f"WARNING: SKIPPED {len(r.skipped)} director(y/ies), left UNTOUCHED:")
            for s in r.skipped[:20]:
                print(f"    SKIPPED: {s['path']}  ({s['reason']})")
            if len(r.skipped) > 20:
                print(f"    ... (+{len(r.skipped) - 20} more)")
        if not apply:
            print("Dry-run: re-run with --apply to execute.")


def run(data_root: Path, opts: MigrationOptions | None = None) -> MigrationReport:
    """Migrate (or, by default, dry-run) a data root and return the report.

    Raises:
        DataRootError: ``opts.apply`` is set and the root is not a directory or
            holds no subject dirs. A dry run on such a root only needs it to be
            a directory.
    """
    opts = opts or MigrationOptions()
    if opts.apply:
        check_data_root(data_root)
    elif not data_root.is_dir():
        raise DataRootError(f"{data_root} is not a directory")
    return Migrator(data_root, opts).run()


# ---------------------------------------------------------------------------
# audit (token census; read-only)


def audit(data_root: Path, subjects: list[str] | None = None) -> tuple[int, dict]:
    """Census the namespace tokens on disk (read-only) and flag anomalies.

    Scans everything, test (``_``-prefixed) subjects included. Prints the
    distinct acq_type / task / session_type / legacy ``session_`` / version
    tokens with counts, and warns on acq_types outside the closed enum and on
    test/calibration tasks missing the leading ``_``. Domain tokens are reported
    but not flagged.

    Returns:
        ``(status, report)``: status is 1 when anything was flagged, else 0, so
        it can gate an ``apply``; report is the JSON-ready census.

    Raises:
        DataRootError: ``data_root`` is not a directory.
    """
    if not data_root.is_dir():
        raise DataRootError(f"{data_root} is not a directory")
    acq_types: Counter = Counter()
    tasks: Counter = Counter()
    session_types: Counter = Counter()
    v3_prefixes: Counter = Counter()
    versions: Counter = Counter()
    unparsed = 0

    subject_dirs = sorted(
        d for d in data_root.iterdir() if d.is_dir() and d.name != QUARANTINE_DIRNAME
    )
    if subjects:
        subject_dirs = [d for d in subject_dirs if d.name in subjects]

    for subject_dir in subject_dirs:
        for container in sorted(d for d in subject_dir.iterdir() if d.is_dir()):
            m = _SESSION_TASK_RE.match(container.name)
            if m:
                v3_prefixes[m.group("task")] += 1
            elif (sm := _SESSION_TYPE_RE.match(container.name)) is not None:
                session_types[sm.group("st")] += 1
            for acq in sorted(d for d in container.iterdir() if d.is_dir()):
                res = target_acq_basename(acq.name)
                if res is None:
                    unparsed += 1
                    continue
                _, info = res
                acq_types[info["acq_type"]] += 1
                if info["task"]:
                    tasks[info["task"]] += 1
                if info["acq_version"] is not None:
                    versions[f"v{info['acq_version']}"] += 1

    def _dump(title: str, counter: Counter) -> None:
        print(f"\n{title}")
        for tok, n in counter.most_common():
            print(f"    {n:6}  {tok}")
        if not counter:
            print("    (none)")

    print(f"NAMESPACE TOKEN AUDIT: {data_root}")
    _dump("acq_type (closed enum):", acq_types)
    _dump("task:", tasks)
    _dump("session_type (container):", session_types)
    _dump("legacy session_<task> containers:", v3_prefixes)
    _dump("version suffixes:", versions)
    if unparsed:
        print(f"\n    {unparsed} dir(s) did not parse as an acquisition (ignored).")

    unknown_acq = sorted(t for t in acq_types if t not in _KNOWN_ACQ_TYPES)
    test_no_us = sorted(t for t in tasks if _TEST_TASK_RE.match(t))

    print("\n" + "=" * 60)
    if unknown_acq:
        print(f"WARNING: acq_type(s) outside the enum {sorted(_KNOWN_ACQ_TYPES)}:")
        for t in unknown_acq:
            print(f"    {t}  ({acq_types[t]})")
    if test_no_us:
        print(
            "WARNING: test/calibration task(s) MISSING the leading '_' "
            "(pollute main datasets): rename to '_<task>':"
        )
        for t in test_no_us:
            print(f"    {t}  ({tasks[t]})  ->  _{t}")
    flagged = bool(unknown_acq or test_no_us)
    if not flagged:
        print("OK: no unknown acq_types and no non-underscored test tasks.")

    report = {
        "data_root": str(data_root),
        "mode": "audit",
        "counts": {
            "acq_type": dict(acq_types),
            "task": dict(tasks),
            "session_type": dict(session_types),
            "legacy_session_containers": dict(v3_prefixes),
            "version": dict(versions),
            "unparsed": unparsed,
        },
        "flags": {
            "unknown_acq_types": unknown_acq,
            "test_tasks_missing_underscore": test_no_us,
        },
        "flagged": flagged,
    }
    return (1 if flagged else 0), report
