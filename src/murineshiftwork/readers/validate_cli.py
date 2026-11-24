"""``msw data validate``: run the session validators over one or more paths.

Each PATH is resolved to the sessions it holds:

- a directory holding MSW files directly (or an ``acquisition_manifest.yaml``)
  is one acquisition: checked with :func:`~.validate.validate_session` and
  :func:`~.namespace.validate_session_namespace`;
- a directory holding a ``session_manifest.yaml`` is a session container:
  checked with :func:`~.container.validate_session_container`, plus the two
  acquisition checks for each behavioural acquisition in it;
- any other directory is searched recursively for the above.

Exit status: 0 when every session is valid, 1 when any has an issue, 2 when a
PATH does not exist or holds no session.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from murineshiftwork.readers.container import (
    _has_recognized_files,
    validate_session_container,
)
from murineshiftwork.readers.namespace import validate_session_namespace
from murineshiftwork.readers.validate import validate_session

_DESCRIPTION = """\
Validate MSW sessions. PATH may be a session container, an acquisition dir,
or any directory holding sessions (searched recursively).
Exit status: 0 all valid, 1 any issue, 2 bad PATH or no session found.
"""


@dataclass
class SessionCheck:
    """Validation outcome for one session container or acquisition dir."""

    path: str
    kind: str  # "container" or "acquisition"
    issues: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.issues


def find_sessions(path: Path) -> list[tuple[str, Path]]:
    """Return ``(kind, dir)`` for every session container/acquisition under ``path``."""
    if _has_recognized_files(path) or (path / "acquisition_manifest.yaml").exists():
        return [("acquisition", path)]
    if (path / "session_manifest.yaml").exists():
        return [("container", path)]
    found: list[tuple[str, Path]] = []
    for child in sorted(path.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            found.extend(find_sessions(child))
    return found


def _acquisition_issues(acq_dir: Path) -> list[str]:
    issues = list(validate_session(acq_dir, verbose=False).issues)
    ns = validate_session_namespace(acq_dir)
    if not ns["valid"]:
        issues.append(f"namespace: {ns['error']}")
    return issues


def _container_issues(container: Path, running_is_issue: bool) -> list[str]:
    report = validate_session_container(container, running_is_issue=running_is_issue)
    issues = [
        f"{b}: on disk but not in session_manifest.yaml"
        for b in report.on_disk_not_in_manifest
    ]
    issues += [
        f"{b}: in session_manifest.yaml but not on disk"
        for b in report.in_manifest_not_on_disk
    ]
    issues += report.status_issues
    for info in report.acquisitions:
        if not info.on_disk:
            continue
        if info.kind == "behaviour":
            issues += [
                f"{info.basename}: {msg}"
                for msg in _acquisition_issues(container / info.basename)
            ]
        elif info.is_complete is False:
            issues.append(f"{info.basename}: incomplete {info.kind} acquisition")
    return issues


def check_session(
    kind: str, path: Path, running_is_issue: bool = False
) -> SessionCheck:
    """Validate one session container or acquisition dir."""
    check = SessionCheck(path=str(path), kind=kind)
    try:
        if kind == "container":
            check.issues = _container_issues(path, running_is_issue)
        else:
            check.issues = _acquisition_issues(path)
    except Exception as exc:  # noqa: BLE001 - unreadable data is a validation finding
        check.issues = [f"validation raised: {exc}"]
    return check


def add_arguments(p: argparse.ArgumentParser) -> None:
    """Add the validate flags to ``p``."""
    p.add_argument("paths", nargs="+", type=Path, metavar="PATH")
    p.add_argument("--json", action="store_true", help="Print a JSON report")
    p.add_argument(
        "--running-is-issue",
        action="store_true",
        help="Report acquisitions whose manifest status is still 'running' "
        "(default: off, a live session is running)",
    )


def execute(args: argparse.Namespace) -> int:
    """Validate every session under ``args.paths``; return the exit status."""
    found: list[tuple[str, Path]] = []
    for path in args.paths:
        if not path.is_dir():
            print(f"Error: not a directory: {path}", file=sys.stderr)
            return 2
        sessions = find_sessions(path)
        if not sessions:
            print(f"Error: no session found under {path}", file=sys.stderr)
            return 2
        found.extend(sessions)
    checks = [check_session(k, p, args.running_is_issue) for k, p in found]
    valid = all(c.valid for c in checks)
    if args.json:
        payload = {
            "valid": valid,
            "sessions": [{**asdict(c), "valid": c.valid} for c in checks],
        }
        print(json.dumps(payload, indent=2))
    else:
        for c in checks:
            if c.valid:
                print(f"OK    {c.path}")
            else:
                n = len(c.issues)
                print(f"FAIL  {c.path} ({n} issue{'' if n == 1 else 's'})")
                for msg in c.issues:
                    print(f"      - {msg}")
    return 0 if valid else 1


def build_parser(prog: str = "msw data validate") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=prog,
        description=_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_arguments(p)
    return p


_ARG_DESTS = ("paths", "json", "running_is_issue")


def _dispatch(**kwargs: object) -> None:
    sys.exit(execute(argparse.Namespace(**{k: kwargs[k] for k in _ARG_DESTS})))


def register(data_sub: argparse._SubParsersAction) -> None:
    """Add ``validate`` to the ``msw data`` subparsers."""
    p = data_sub.add_parser(
        "validate",
        help="Validate session containers and acquisitions",
        description=_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_arguments(p)
    p.set_defaults(func=_dispatch)
