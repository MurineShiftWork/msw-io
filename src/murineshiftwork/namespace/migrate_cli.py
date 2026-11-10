"""Command line for the namespace migration: ``msw-io-migrate`` and ``msw data migrate``.

Both entry points share :func:`add_arguments` and :func:`execute`, so they take
the same flags and return the same exit status: 0 when clean, 1 when collisions
were left in place (or, with ``--audit``, when anything was flagged), 2 when the
data root is refused.

``msw data migrate`` is registered through the ``msw.cli`` entry point group;
the ``msw`` parser calls :func:`register` with its subparsers and later calls the
selected ``func`` with every parsed argument as a keyword.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from murineshiftwork.namespace import migrate as _m

_DESCRIPTION = """\
Migrate MSW data directories to the current namespace shape, in place.
Dry run by default; pass --apply to execute.

Operator sequence per data root:
  msw-io-migrate ROOT --audit
  msw-io-migrate ROOT --report dry_run.json
  (review dry_run.json)
  msw-io-migrate ROOT --apply --report applied.json
  msw-io-migrate ROOT --audit
"""


def add_arguments(p: argparse.ArgumentParser) -> None:
    """Add the migration flags to ``p``."""
    p.add_argument("data_root", type=Path, help="Directory holding the subject dirs")
    p.add_argument("--apply", action="store_true", help="Migrate (default: dry run)")
    p.add_argument("--subjects", nargs="+", metavar="SUBJECT")
    p.add_argument("--level", choices=_m.LEVELS, default="acquisition")
    p.add_argument(
        "--acq-type",
        default="all",
        help="Only this acq_type (msw, video_flir, ...). Default: all",
    )
    p.add_argument(
        "--shape",
        choices=_m.SHAPES,
        default="all",
        help="Only this shape (incremental rollout). Default: all",
    )
    p.add_argument(
        "--on-conflict",
        choices=_m.ON_CONFLICT,
        default="skip",
        help="Target exists: skip (default), quarantine (move aside), or delete "
        "(byte-identical duplicates only; conflicts are quarantined)",
    )
    p.add_argument(
        "--quarantine-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help=f"Quarantine root. Default: DATA_ROOT/{_m.QUARANTINE_DIRNAME}",
    )
    p.add_argument(
        "--no-create-manifests",
        dest="create_manifests",
        action="store_false",
        help="Do not create manifests where absent (default: create + stamp)",
    )
    p.add_argument(
        "--include-test",
        action="store_true",
        help="Include _-prefixed subject and acquisition dirs (default: skip)",
    )
    p.add_argument(
        "--flatten-optotagging",
        action="store_true",
        help="Flatten legacy __optotagging subprotocol subdirs into peer video_rce "
        "acquisitions. Without it they are reported as skipped.",
    )
    p.add_argument(
        "--audit",
        action="store_true",
        help="Read-only token census; exits non-zero if anything is flagged",
    )
    p.add_argument(
        "--report",
        type=Path,
        default=None,
        metavar="FILE",
        help="Write a JSON report of every action, conflict and skip",
    )


def execute(args: argparse.Namespace) -> int:
    """Run the audit or migration described by parsed ``args``; return the exit status."""
    try:
        if args.audit:
            status, report = _m.audit(args.data_root, args.subjects)
        else:
            opts = _m.MigrationOptions(
                apply=args.apply,
                subjects=args.subjects,
                level=args.level,
                acq_type=args.acq_type,
                shape=args.shape,
                on_conflict=args.on_conflict,
                quarantine_dir=args.quarantine_dir,
                create_manifests=args.create_manifests,
                include_test=args.include_test,
                flatten_optotagging=args.flatten_optotagging,
            )
            result = _m.run(args.data_root, opts)
            status = 1 if result.unresolved else 0
            report = result.to_dict()
    except _m.DataRootError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if args.report is not None:
        _m.write_report(report, args.report)
        print(f"Report written to {args.report}")
    return status


def build_parser(prog: str = "msw-io-migrate") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=prog,
        description=_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_arguments(p)
    return p


def main(argv: list[str] | None = None) -> None:
    """Console entry point ``msw-io-migrate``."""
    sys.exit(execute(build_parser().parse_args(argv)))


_ARG_DESTS = (
    "data_root",
    "apply",
    "subjects",
    "level",
    "acq_type",
    "shape",
    "on_conflict",
    "quarantine_dir",
    "create_manifests",
    "include_test",
    "flatten_optotagging",
    "audit",
    "report",
)


def _dispatch(**kwargs: object) -> None:
    ns = argparse.Namespace(**{k: kwargs[k] for k in _ARG_DESTS})
    sys.exit(execute(ns))


def register(sub_parsers: argparse._SubParsersAction) -> None:
    """Add ``msw data migrate`` to the ``msw`` command line (``msw.cli`` plugin)."""
    data = sub_parsers.add_parser("data", help="Data tree tools (msw-io)")
    data_sub = data.add_subparsers(dest="data_command", metavar="command")
    data_sub.required = True
    mig = data_sub.add_parser(
        "migrate",
        help="Migrate data dirs to the current namespace (dry run by default)",
        description=_DESCRIPTION.replace("msw-io-migrate", "msw data migrate"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_arguments(mig)
    mig.set_defaults(func=_dispatch)
