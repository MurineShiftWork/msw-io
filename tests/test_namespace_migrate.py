"""Namespace migration on synthetic data trees: dry run, apply, re-run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
import yaml

from murineshiftwork.namespace import migrate_cli
from murineshiftwork.namespace.migrate import (
    DataRootError,
    MigrationOptions,
    audit,
    check_data_root,
    run,
)

SUB = "s001"


def _write(p: Path, text: str = "x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _acq(root: Path, container: str, name: str, subject: str = SUB) -> Path:
    """Acquisition dir with a session yaml, a JSON sidecar and a data file."""
    d = root / subject / container / name
    _write(d / f"{name}.msw.session.yaml", yaml.safe_dump({"basename": name}))
    _write(d / f"{name}.msw.settings.task.json", json.dumps({"ref": f"{name}.msw"}))
    _write(d / f"{name}.msw.df.jsonl", "{}\n")
    return d


def _tree(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


def _mig(root: Path, *argv: str) -> int:
    with pytest.raises(SystemExit) as exc:
        migrate_cli.main([str(root), *argv])
    return int(exc.value.code or 0)


def _cycle(root: Path, *argv: str) -> None:
    """Dry run leaves the tree alone; apply migrates; a second apply is a no-op."""
    before = _tree(root)
    assert _mig(root, *argv) == 0
    assert _tree(root) == before
    assert _mig(root, "--apply", *argv) == 0
    after = _tree(root)
    assert after != before
    report = root.parent / "rerun.json"
    assert _mig(root, "--apply", "--report", str(report), *argv) == 0
    assert _tree(root) == after
    assert json.loads(report.read_text(encoding="utf-8"))["actions"] == []


def _manifest(d: Path, name: str) -> dict:
    return yaml.safe_load((d / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("old", "new", "task_version"),
    [
        ("{dt}__gonogo", "{dt}__msw__gonogo", None),
        ("{dt}__gonogo__v2", "{dt}__msw__gonogo", 2),
        ("{dt}__msw__gonogo__v3", "{dt}__msw__gonogo", 3),
        ("{dt}__video_flir__v1", "{dt}__video_flir", 1),
        ("{dt}__msw__test_lick", "{dt}__msw___test_lick", None),
    ],
)
def test_acquisition_shapes(tmp_path, old, new, task_version):
    root = tmp_path / "data"
    dt = f"{SUB}__20260101_120000_000001"
    old, new = old.format(dt=dt), new.format(dt=dt)
    _acq(root, dt, old)
    _write(root / SUB / dt / old / "sub" / f"{old}.msw.sub.csv", "a,b\n")

    _cycle(root)

    acq = root / SUB / dt / new
    assert not (root / SUB / dt / old).exists()
    assert sorted(p.name for p in acq.iterdir() if p.is_file()) == sorted(
        [
            "acquisition_manifest.yaml",
            f"{new}.msw.df.jsonl",
            f"{new}.msw.session.yaml",
            f"{new}.msw.settings.task.json",
        ]
    )
    assert (acq / "sub" / f"{new}.msw.sub.csv").exists()
    assert (
        yaml.safe_load((acq / f"{new}.msw.session.yaml").read_text())["basename"] == new
    )
    assert json.loads((acq / f"{new}.msw.settings.task.json").read_text())["ref"] == (
        f"{new}.msw"
    )
    am = _manifest(acq, "acquisition_manifest.yaml")
    assert am["acquisition_name"] == new
    assert am["msw_namespace_version"] == "4.3"
    assert (am.get("metadata") or {}).get("task_version") == task_version
    sm = _manifest(root / SUB / dt, "session_manifest.yaml")
    assert [a["basename"] for a in sm["acquisitions"]] == [new]


def test_existing_manifests_are_updated(tmp_path):
    root = tmp_path / "data"
    dt = f"{SUB}__20260101_120000_000001"
    old, new = f"{dt}__gonogo__v2", f"{dt}__msw__gonogo"
    acq = _acq(root, dt, old)
    _write(
        acq / "acquisition_manifest.yaml",
        yaml.safe_dump({"acquisition_name": old, "files": [f"{old}.msw.df.jsonl"]}),
    )
    _write(
        root / SUB / dt / "session_manifest.yaml",
        yaml.safe_dump(
            {"msw_namespace_version": "4.0", "acquisitions": [{"basename": old}]}
        ),
    )
    _cycle(root)
    am = _manifest(root / SUB / dt / new, "acquisition_manifest.yaml")
    assert am["files"] == [f"{new}.msw.df.jsonl"]
    assert am["metadata"] == {"task_version": 2, "source": "namespace_migration"}
    sm = _manifest(root / SUB / dt, "session_manifest.yaml")
    assert sm["acquisitions"] == [{"basename": new}]
    assert sm["msw_namespace_version"] == "4.3"


def test_no_create_manifests(tmp_path):
    root = tmp_path / "data"
    dt = f"{SUB}__20260101_120000_000001"
    _acq(root, dt, f"{dt}__gonogo")
    _cycle(root, "--no-create-manifests")
    assert not (root / SUB / dt / "session_manifest.yaml").exists()
    assert not (
        root / SUB / dt / f"{dt}__msw__gonogo" / "acquisition_manifest.yaml"
    ).exists()


def test_v3_session_container(tmp_path):
    root = tmp_path / "data"
    dt = f"{SUB}__20260101_120000_000001"
    container = f"{dt}__session_gonogo"
    _acq(root, container, f"{dt}__gonogo")
    _cycle(root, "--level", "all")
    new = root / SUB / dt
    assert not (root / SUB / container).exists()
    assert (new / f"{dt}__msw__gonogo" / f"{dt}__msw__gonogo.msw.df.jsonl").exists()
    assert _manifest(new, "session_manifest.yaml")["session_name"] == dt


def test_level_acquisition_leaves_container(tmp_path):
    root = tmp_path / "data"
    dt = f"{SUB}__20260101_120000_000001"
    _acq(root, f"{dt}__session_gonogo", f"{dt}__gonogo")
    _cycle(root)
    assert (root / SUB / f"{dt}__session_gonogo" / f"{dt}__msw__gonogo").is_dir()


def test_filters_shape_and_acq_type(tmp_path):
    root = tmp_path / "data"
    dt = f"{SUB}__20260101_120000_000001"
    _acq(root, dt, f"{dt}__gonogo")
    _acq(root, dt, f"{dt}__video_flir__v1")
    assert _mig(root, "--apply", "--shape", "legacy3comp") == 0
    names = {p.name for p in (root / SUB / dt).iterdir() if p.is_dir()}
    assert names == {f"{dt}__msw__gonogo", f"{dt}__video_flir__v1"}
    assert _mig(root, "--apply", "--acq-type", "video_flir") == 0
    names = {p.name for p in (root / SUB / dt).iterdir() if p.is_dir()}
    assert names == {f"{dt}__msw__gonogo", f"{dt}__video_flir"}


def test_test_subject_needs_include_test(tmp_path):
    root = tmp_path / "data"
    subj = "_test_subject"
    dt = f"{subj}__20260101_120000_000001"
    _acq(root, f"{SUB}__20260101_120000_000001", f"{SUB}__20260101_120000_000001__msw")
    _acq(root, dt, f"{dt}__msw__test_lick", subject=subj)
    before = _tree(root)
    assert _mig(root, "--apply") == 0
    assert _tree(root) == before
    assert _mig(root, "--audit") == 1
    _cycle(root, "--include-test")
    assert (root / subj / dt / f"{dt}__msw___test_lick").is_dir()
    assert _mig(root, "--audit") == 0


def _opto_tree(root: Path) -> tuple[Path, str]:
    container = root / SUB / f"{SUB}__20260527_130000_000001__ephys"
    _acq(root, container.name, f"{SUB}__20260527_130000_000001__pxi")
    parent = container / f"{SUB}__20260527_133053_901389__optotagging"
    for sub, ts in (("power_ramp", "20260527133100"), ("pulse", "20260527133500")):
        child = parent / f"{parent.name}__{sub}"
        prefix = f"{parent.name}_{sub}"
        _write(child / f"{prefix}.rce.rpi-1.{ts}.mp4", "video")
        _write(
            child / f"{prefix}.rce.rpi-1.{ts}.yaml",
            yaml.safe_dump({"path": f"{parent.name}/{child.name}/{prefix}.mp4"}),
        )
    return container, parent.name


def test_optotagging_reported_without_flag(tmp_path):
    root = tmp_path / "data"
    container, parent = _opto_tree(root)
    report = tmp_path / "r.json"
    assert _mig(root, "--report", str(report)) == 0
    skipped = json.loads(report.read_text())["skipped"]
    assert [s["path"] for s in skipped] == [f"{SUB}/{container.name}/{parent}"]
    assert _mig(root, "--apply") == 0
    assert (container / parent).is_dir()


def test_optotagging_flatten(tmp_path):
    root = tmp_path / "data"
    container, parent = _opto_tree(root)
    _cycle(root, "--flatten-optotagging")
    assert not (container / parent).exists()
    for sub, dt in (("power_ramp", "20260527_133100"), ("pulse", "20260527_133500")):
        tgt = container / f"{SUB}__{dt}__video_rce"
        ts = dt.replace("_", "")
        assert (tgt / f"{tgt.name}.rce.rpi-1.{ts}.mp4").read_text() == "video"
        side = yaml.safe_load((tgt / f"{tgt.name}.rce.rpi-1.{ts}.yaml").read_text())
        assert side["path"] == f"{tgt.name}/{tgt.name}.mp4"
        md = _manifest(tgt, "acquisition_manifest.yaml")["metadata"]
        assert md["optotagging_subprotocol"] == sub
        assert md["optotagging_session"] == parent
    sm = _manifest(container, "session_manifest.yaml")
    assert [a["basename"] for a in sm["acquisitions"]] == [
        f"{SUB}__20260527_133100__video_rce",
        f"{SUB}__20260527_133500__video_rce",
    ]


def _collision(root: Path, same: bool) -> tuple[Path, Path]:
    dt = f"{SUB}__20260101_120000_000001"
    old = root / SUB / f"{dt}__session_gonogo"
    new = root / SUB / dt
    _write(old / f"{dt}__msw__gonogo" / "data.bin", "abc")
    _write(new / f"{dt}__msw__gonogo" / "data.bin", "abc" if same else "abcdef")
    return old, new


@pytest.mark.parametrize(
    ("same", "mode", "code", "old_left", "quarantined", "resolution"),
    [
        (True, "skip", 1, True, False, "skip"),
        (False, "skip", 1, True, False, "skip"),
        (True, "delete", 0, False, False, "delete"),
        (False, "delete", 0, False, True, "quarantine"),
        (True, "quarantine", 0, False, True, "quarantine"),
        (False, "quarantine", 0, False, True, "quarantine"),
    ],
)
def test_collisions(tmp_path, same, mode, code, old_left, quarantined, resolution):
    root = tmp_path / "data"
    old, new = _collision(root, same)
    before = _tree(root)
    report = tmp_path / "r.json"
    args = ("--level", "container", "--on-conflict", mode, "--report", str(report))
    assert _mig(root, *args) == code
    assert _tree(root) == before
    (conflict,) = json.loads(report.read_text())["conflicts"]
    assert conflict["classification"] == ("DUPLICATE" if same else "CONFLICT")
    assert conflict["resolution"] == resolution

    assert _mig(root, "--apply", *args) == code
    assert old.exists() == old_left
    assert (new / f"{SUB}__20260101_120000_000001__msw__gonogo" / "data.bin").exists()
    q = root / "_migration_quarantine" / SUB / old.name
    assert q.exists() == quarantined
    if quarantined:
        assert _mig(root, "--apply", *args) == 0


def test_quarantine_dir_option(tmp_path):
    root = tmp_path / "data"
    old, _ = _collision(root, same=False)
    qdir = tmp_path / "quarantine"
    args = ["--apply", "--level", "container", "--on-conflict", "quarantine"]
    assert _mig(root, *args, "--quarantine-dir", str(qdir)) == 0
    assert (
        qdir / SUB / old.name / f"{SUB}__20260101_120000_000001__msw__gonogo"
    ).is_dir()


def test_acquisition_conflict_is_quarantined_not_deleted(tmp_path):
    root = tmp_path / "data"
    dt = f"{SUB}__20260101_120000_000001"
    _acq(root, dt, f"{dt}__gonogo")
    _acq(root, dt, f"{dt}__msw__gonogo")
    assert _mig(root, "--apply", "--on-conflict", "delete") == 0
    q = root / "_migration_quarantine" / dt / f"{dt}__gonogo"
    assert (q / f"{dt}__gonogo.msw.df.jsonl").exists()


def test_report_lists_actions(tmp_path):
    root = tmp_path / "data"
    dt = f"{SUB}__20260101_120000_000001"
    _acq(root, dt, f"{dt}__gonogo__v2")
    report = tmp_path / "out" / "dry.json"
    assert _mig(root, "--report", str(report)) == 0
    data = json.loads(report.read_text())
    assert data["mode"] == "dry-run"
    assert data["summary"]["migrated"] == 1
    (action,) = data["actions"]
    assert action["path"] == f"{SUB}/{dt}/{dt}__gonogo__v2"
    assert action["target"] == f"{SUB}/{dt}/{dt}__msw__gonogo"
    assert action["task_version"] == 2
    assert action["applied"] is False
    assert {f["target"] for f in action["files"]} == {
        f"{dt}__msw__gonogo.msw.session.yaml",
        f"{dt}__msw__gonogo.msw.settings.task.json",
        f"{dt}__msw__gonogo.msw.df.jsonl",
    }


def test_audit_report(tmp_path):
    root = tmp_path / "data"
    dt = f"{SUB}__20260101_120000_000001"
    _acq(root, f"{dt}__session_gonogo", f"{dt}__gonogo__v2")
    _acq(root, dt, f"{dt}__msw__calibration_valve")
    status, report = audit(root)
    assert status == 1
    assert report["counts"]["version"] == {"v2": 1}
    assert report["counts"]["legacy_session_containers"] == {"gonogo": 1}
    assert report["flags"]["test_tasks_missing_underscore"] == ["calibration_valve"]


def test_apply_refuses_bad_root(tmp_path):
    assert _mig(tmp_path / "missing", "--apply") == 2
    assert _mig(tmp_path / "missing") == 2
    root = tmp_path / "data"
    dt = f"{SUB}__20260101_120000_000001"
    _acq(root, dt, f"{dt}__gonogo")
    # a subject dir passed instead of the data root
    before = _tree(root)
    assert _mig(root / SUB, "--apply") == 2
    assert _tree(root) == before
    with pytest.raises(DataRootError):
        check_data_root(root / SUB / dt)
    with pytest.raises(DataRootError):
        run(tmp_path / "empty_does_not_exist", MigrationOptions(apply=True))


def test_msw_plugin_registers_data_migrate(tmp_path):
    root = tmp_path / "data"
    dt = f"{SUB}__20260101_120000_000001"
    _acq(root, dt, f"{dt}__gonogo")
    parser = argparse.ArgumentParser(prog="msw")
    sub = parser.add_subparsers(dest="command")
    migrate_cli.register(sub)
    args = vars(parser.parse_args(["data", "migrate", str(root), "--apply"]))
    with pytest.raises(SystemExit) as exc:
        args["func"](**args)
    assert exc.value.code == 0
    assert (root / SUB / dt / f"{dt}__msw__gonogo").is_dir()
