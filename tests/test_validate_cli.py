"""``msw data validate`` and the acquisition status vocabulary."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import pytest

from murineshiftwork.namespace import migrate_cli
from murineshiftwork.namespace.manifest import (
    ACQUISITION_STATUSES,
    append_acquisition_to_session,
    finalize_acquisition_in_session,
)
from murineshiftwork.readers import validate_session_container
from murineshiftwork.readers.validate_cli import build_parser, execute

_FIXTURE = Path(__file__).parent / "data" / "fixture_v42"
_CONTAINER = "_test_subject__20260619_120000_000000"
_ACQ = f"{_CONTAINER}__sequence__v1"
_FLIR = f"{_CONTAINER}__video_flir__v1"


def _container(root: Path, name: str = "c1") -> Path:
    """Copy the v4.2 fixture container (one complete behavioural acquisition)."""
    dst = root / name / _CONTAINER
    shutil.copytree(_FIXTURE / _CONTAINER, dst)
    return dst


def _run(*argv: str) -> int:
    return execute(build_parser().parse_args([str(a) for a in argv]))


def test_valid_container_exits_zero(tmp_path, capsys):
    c = _container(tmp_path)
    assert _run(c) == 0
    assert capsys.readouterr().out.startswith(f"OK    {c}")


def test_recurses_and_reports_issues(tmp_path, capsys):
    good = _container(tmp_path, "a")
    bad = _container(tmp_path, "b")
    (bad / _FLIR).mkdir()  # camera acquisition on disk, not in the manifest
    assert _run(tmp_path) == 1
    out = capsys.readouterr().out
    assert f"OK    {good}" in out
    assert f"FAIL  {bad} (1 issue)" in out
    assert f"{_FLIR}: on disk but not in session_manifest.yaml" in out


def test_json_output(tmp_path, capsys):
    c = _container(tmp_path)
    finalize_acquisition_in_session(c, _ACQ, status="aborted")
    assert _run(c, "--json") == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False
    [s] = payload["sessions"]
    assert s["kind"] == "container"
    assert s["issues"] == [f"{_ACQ}: ended with status 'aborted'"]


def test_acquisition_dir_checked_directly(tmp_path, capsys):
    acq = _container(tmp_path) / _ACQ
    (acq / f"{_ACQ}.msw.session.yaml").unlink()
    (acq / f"{_ACQ}.msw.df.jsonl").unlink()
    (acq / "acquisition_manifest.yaml").write_text("type: acquisition\n")
    assert _run(acq) == 1
    assert "Incomplete MSW session" in capsys.readouterr().out


def test_running_is_issue_only_when_asked(tmp_path):
    c = _container(tmp_path)
    append_acquisition_to_session(c, _FLIR)  # status=running, not on disk
    (c / _FLIR).mkdir()
    assert _run(c) == 0
    assert _run(c, "--running-is-issue") == 1


@pytest.mark.parametrize("bad", ["missing", "empty"])
def test_bad_path_exits_two(tmp_path, bad):
    path = tmp_path / bad
    if bad == "empty":
        path.mkdir()
    assert _run(path) == 2


def test_msw_plugin_registers_data_validate(tmp_path):
    c = _container(tmp_path)
    parser = argparse.ArgumentParser(prog="msw")
    migrate_cli.register(parser.add_subparsers(dest="command"))
    args = vars(parser.parse_args(["data", "validate", str(c)]))
    with pytest.raises(SystemExit) as exc:
        args["func"](**args)
    assert exc.value.code == 0


# --- status vocabulary ---


def test_status_vocabulary():
    assert ACQUISITION_STATUSES == (
        "running",
        "complete",
        "stopped",
        "aborted",
        "interrupted",
        "partial",
        "failed",
    )


@pytest.mark.parametrize(
    ("status", "issue"),
    [
        ("complete", None),
        ("stopped", None),
        ("running", None),
        ("aborted", "ended with status 'aborted'"),
        ("interrupted", "ended with status 'interrupted'"),
        ("partial", None),
        ("failed", "ended with status 'failed'"),
        ("paused", "unknown status 'paused'"),
    ],
)
def test_container_status_issues(tmp_path, status, issue):
    c = _container(tmp_path)
    finalize_acquisition_in_session(c, _ACQ, status=status)  # writer accepts any
    report = validate_session_container(c)
    assert report.status_issues == ([f"{_ACQ}: {issue}"] if issue else [])


def test_container_running_flag(tmp_path):
    c = _container(tmp_path)
    finalize_acquisition_in_session(c, _ACQ, status="running")
    report = validate_session_container(c, running_is_issue=True)
    assert report.status_issues == [f"{_ACQ}: status 'running'"]


def test_remote_entry_is_not_missing(tmp_path, capsys):
    c = _container(tmp_path)
    remote = f"{_CONTAINER}__ephys__v1"
    append_acquisition_to_session(
        c,
        remote,
        extra={
            "location": "remote",
            "host": "ephys-host",
            "path": "D:/recordings/x",
            "backend": "openephys",
        },
    )
    finalize_acquisition_in_session(c, remote, status="stopped")
    report = validate_session_container(c)
    assert report.remote == [remote]
    assert report.in_manifest_not_on_disk == []
    assert report.is_consistent
    assert _run(c) == 0
    assert capsys.readouterr().out.startswith(f"OK    {c}")
