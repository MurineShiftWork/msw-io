"""Config model v3: loader, resolver and the resolved run payload.

The example tree in ``tests/data/config_v3`` has two machines, four setups, two tasks
with modes and three subjects. The full payloads of the example runs are kept as golden
files; set ``MSW_REGEN_GOLDEN=1`` to rewrite them after an intended change.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from murineshiftwork.config import (
    ConfigDocument,
    ConfigError,
    ContentHashError,
    RequirementError,
    ResolvedRun,
    RunSource,
    SchemaVersionError,
    UnknownNameError,
    UnresolvedReferenceError,
    load_config,
    merge_fragments,
    resolve,
)
from murineshiftwork.config.merge import from_pointer, to_pointer

DATA = Path(__file__).parent / "data"
TREE = DATA / "config_v3"
GOLDEN = DATA / "config_v3_golden"
HOST_FILE = TREE / "host-local" / "machine-b.msw-machine.yaml"

# Level 0: stand-in for the task packages' own defaults.
PACKAGE_DEFAULTS: dict[str, dict[str, Any]] = {
    "sequence": {
        "barcode": {"bit_duration_ms": 35.0, "bits": 20},
        "sound": {"reward": {"frequency": -1, "duration_s": 0.2, "amplitude": 0.15}},
        "tasks": {
            "sequence": {
                "curriculum": {"enabled": False},
                "reward_perturbation": {"enabled": False},
                "reward": {"amount_ul": 3.0},
            }
        },
    },
    "probabilistic_switching": {
        "barcode": {"bit_duration_ms": 35.0, "bits": 20},
        "cameras": {"record": {"video": False}},
        "tasks": {"probabilistic_switching": {"n_max_trials": 1500}},
    },
}

PS = "/tasks/probabilistic_switching"


@pytest.fixture
def config():
    return load_config(TREE, source=RunSource(revision="rev-1"))


def run_of(config, setup, subject, task, **kw):
    return resolve(
        config, setup, subject, task, package_defaults=PACKAGE_DEFAULTS[task], **kw
    )


def settings_levels(run: ResolvedRun) -> dict[str, tuple[Any, str]]:
    """Settings leaves as ``{pointer: (value, level)}``, without the settings prefix."""
    out = {}
    for pointer, src in run.provenance.items():
        path = from_pointer(pointer)
        if path[0] != "settings":
            continue
        value: Any = run.settings
        for key in path[1:]:
            value = value[key]
        out[to_pointer(path[1:])] = (value, src.level)
    return out


def check_golden(name: str, run: ResolvedRun) -> None:
    path = GOLDEN / f"{name}.json"
    text = run.to_json(indent=2) + "\n"
    if os.environ.get("MSW_REGEN_GOLDEN"):
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert json.loads(text) == json.loads(path.read_text(encoding="utf-8"))


# --- loader ------------------------------------------------------------------


def test_loader_reads_sections_in_order(config):
    assert config.files[:2] == ["machines/machine-a.yaml", "machines/machine-b.yaml"]
    assert config.files[-1] == "subjects/lgcyX2.yaml"
    assert [f.split("/")[0] for f in config.files] == sorted(
        (f.split("/")[0] for f in config.files),
        key=["machines", "setups", "tasks", "subjects"].index,
    )
    assert set(config.document.setups) == {"alfa", "bravo", "setup-1", "setup-2"}
    assert config.sources[("setups", "alfa", "machine")] == "setups/alfa.yaml"
    assert config.document.machines["machine-a"].boxes["kappa"].valves[2].calibration


def test_extra_file_wins_and_is_labelled(config, tmp_path):
    outside = tmp_path / "override.yaml"
    outside.write_text(
        "schema_version: 3\nmachines: {machine-b: {os: linux-test}}\n",
        encoding="utf-8",
    )
    loaded = load_config(TREE, [HOST_FILE, outside])
    machine = loaded.document.machines["machine-b"]
    assert machine.paths == {"config_dir": "/data/configs", "data_dir": "/data/local"}
    assert machine.os == "linux-test"
    key = ("machines", "machine-b", "paths", "data_dir")
    assert loaded.sources[key] == "host-local/machine-b.msw-machine.yaml"
    assert loaded.sources[("machines", "machine-b", "os")] == "override.yaml"


def test_merge_replaces_subtree_and_its_provenance():
    loaded = merge_fragments(
        [
            ("a", {"schema_version": 3, "tasks": {"t": {"settings": {"x": {"y": 1}}}}}),
            ("b", {"schema_version": 3, "tasks": {"t": {"settings": {"x": [1, 2]}}}}),
            ("c", {"schema_version": 3, "tasks": {"t": {"settings": {}}}}),
        ]
    )
    assert loaded.document.tasks["t"].settings == {"x": [1, 2]}
    assert loaded.sources == {("tasks", "t", "settings", "x"): "b"}


@pytest.mark.parametrize("version", [None, 2, 4, "3"])
def test_loader_refuses_other_schema_versions(tmp_path, version):
    shutil.copytree(TREE, tmp_path / "cfg")
    bad = tmp_path / "cfg" / "setups" / "alfa.yaml"
    data = yaml.safe_load(bad.read_text(encoding="utf-8"))
    if version is None:
        del data["schema_version"]
    else:
        data["schema_version"] = version
    bad.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(SchemaVersionError, match=r"setups/alfa\.yaml"):
        load_config(tmp_path / "cfg")


def test_loader_refuses_unknown_keys():
    with pytest.raises(ConfigError, match="unknown top-level keys"):
        merge_fragments([("f", {"schema_version": 3, "machine": {}})])
    with pytest.raises(ValidationError, match="usess"):
        merge_fragments(
            [
                (
                    "f",
                    {
                        "schema_version": 3,
                        "setups": {"s": {"machine": "m", "usess": {}}},
                    },
                )
            ]
        )


def test_devices_keep_unknown_fields(config):
    stage = config.document.machines["machine-b"].devices["stage-1"]
    assert stage.type == "stage_tower"
    assert stage.model_extra is not None
    assert stage.model_extra["axes"]["x"]["id"] == 11


# --- resolver: the three example runs ------------------------------------------


def test_alfa_lgcyx1_sequence(config):
    run = run_of(config, "alfa", "lgcyX1", "sequence")
    assert settings_levels(run) == {
        "/barcode/bit_duration_ms": (35.0, "defaults"),
        "/barcode/bits": (20, "defaults"),
        "/sound/reward/frequency": (10000, "subject"),
        "/sound/reward/duration_s": (0.1, "subject"),
        "/sound/reward/amplitude": (0.1, "subject"),
        "/tasks/sequence/curriculum/enabled": (True, "task"),
        "/tasks/sequence/curriculum/defaults/reward/final_plateau": (3.0, "subject"),
        "/tasks/sequence/reward_perturbation/enabled": (True, "subject"),
        "/tasks/sequence/reward_perturbation/target": ("position", "subject"),
        "/tasks/sequence/reward_perturbation/distribution/4": (
            [{"amount_ul": 50.0, "probability": 0.02}],
            "subject",
        ),
        "/tasks/sequence/reward/amount_ul": (3.0, "defaults"),
        "/calibration_policy/stale_days": (180, "setup"),
    }
    assert run.machine.name == "machine-a"
    assert run.uses == {"bpod": "bpod-a", "box": "kappa", "sound": "speaker-a"}
    assert set(run.devices) == {"bpod-a", "speaker-a"}
    assert set(run.boxes) == {"kappa"}
    assert run.state == {"curriculum": {"level": 12, "updated": "2026-10-16T16:59:47"}}
    assert run.secrets == {"/machine/services/labwatch/token": "labwatch_token"}
    assert run.source == RunSource(revision="rev-1")
    prov = run.provenance
    assert (
        prov["/settings/tasks/sequence/curriculum/enabled"].file
        == "tasks/sequence.yaml"
    )
    assert prov["/settings/barcode/bits"].file is None
    assert prov["/boxes/kappa/valves/2/calibration/points"].file == (
        "machines/machine-a.yaml"
    )
    assert prov["/state/curriculum/level"].file == "subjects/lgcyX1.yaml"
    check_golden("alfa__lgcyX1__sequence", run)


def test_setup1_lgcyx2_pswitch_habituation_with_override(config):
    overrides = {"tasks": {"probabilistic_switching": {"n_max_trials": 100}}}
    run = run_of(
        config,
        "setup-1",
        "lgcyX2",
        "probabilistic_switching",
        mode="habituation",
        run_overrides=overrides,
    )
    levels = settings_levels(run)
    # A subject wins over a mode; the run wins over both.
    assert levels[f"{PS}/reward_amount_ul"] == (2.5, "subject")
    assert levels[f"{PS}/n_max_trials"] == (100, "run")
    assert levels[f"{PS}/probabilities"] == ([[100, 99], [99, 100]], "mode")
    assert levels[f"{PS}/min_block_length"] == (20, "task")
    assert levels["/barcode/bit_duration_ms"] == (100.0, "setup")
    assert levels["/barcode/bits"] == (20, "defaults")
    assert levels["/cameras/record/video"] == (True, "task")
    assert levels["/cameras/record/cameras"] == (["face", "body"], "subject")
    assert levels["/cameras/failure"] == ("continue", "setup")
    assert levels["/hooks/post_task"] == (["weigh_subject"], "setup")
    assert len(levels) == 20
    # Option (b): the subject's sequence block does not reach this task.
    assert set(run.settings["tasks"]) == {"probabilistic_switching"}
    mode_src = run.provenance[f"/settings{PS}/probabilities"]
    assert mode_src.file == "tasks/probabilistic_switching.yaml"
    assert run.provenance[f"/settings{PS}/n_max_trials"].file is None
    # Referenced camera config is inlined, with its hash and source.
    cams = run.devices["cams-1"].model_extra or {}
    assert cams["config"]["file"] == "device_configs/cameras/setup-1.cameras.yaml"
    assert set(cams["config"]["content"]["cameras"]) == {"face", "body"}
    assert len(cams["config"]["content_sha256"]) == 64
    src = run.provenance["/devices/cams-1/config/content/cameras/face/fps"]
    assert src.file == "device_configs/cameras/setup-1.cameras.yaml"
    assert run.provenance["/devices/cams-1/config/file"].file == (
        "machines/machine-b.yaml"
    )
    assert run.secrets == {"/machine/services/logagent/token": "logagent_token"}
    assert set(run.devices) == {"bpod-1", "stage-1", "scale-1", "speaker-1", "cams-1"}
    check_golden("setup-1__lgcyX2__probabilistic_switching__habituation", run)


def test_alfa_refuses_pswitch_without_cameras(config):
    with pytest.raises(RequirementError, match=r"\['cameras'\].*setup 'alfa'"):
        run_of(config, "alfa", "lgcyX2", "probabilistic_switching")


def test_payload_has_no_file_references(config):
    run = run_of(config, "setup-1", "lgcyX2", "probabilistic_switching")
    text = run.to_json()
    assert '"config":"device_configs' not in text
    with pytest.raises(UnresolvedReferenceError):
        resolve(config.document, "setup-1", "lgcyX2", "probabilistic_switching")


def test_reference_outside_root_is_refused(tmp_path):
    shutil.copytree(TREE, tmp_path / "cfg")
    machine = tmp_path / "cfg" / "machines" / "machine-b.yaml"
    text = machine.read_text(encoding="utf-8").replace(
        "device_configs/cameras/setup-1", "../secrets/setup-1"
    )
    machine.write_text(text, encoding="utf-8")
    with pytest.raises(UnresolvedReferenceError, match="relative to the config root"):
        run_of(
            load_config(tmp_path / "cfg"),
            "setup-1",
            "lgcyX2",
            "probabilistic_switching",
        )


@pytest.mark.parametrize(
    ("args", "match"),
    [
        (("nosuch", "lgcyX1", "sequence"), "unknown setup"),
        (("alfa", "nosuch", "sequence"), "unknown subject"),
        (("alfa", "lgcyX1", "sequence", "nosuch"), "no mode 'nosuch'"),
    ],
)
def test_unknown_names(config, args, match):
    with pytest.raises(UnknownNameError, match=match):
        resolve(config, *args)


def test_bare_document_resolves_without_files(config):
    doc = ConfigDocument.model_validate(config.document.model_dump(mode="json"))
    run = resolve(doc, "alfa", "lgcyX1", "sequence")
    assert all(src.file is None for src in run.provenance.values())
    assert run.settings["tasks"]["sequence"]["curriculum"]["enabled"] is True


# --- payload: round trip and hash ---------------------------------------------


def test_json_and_yaml_round_trip(config):
    run = run_of(config, "setup-1", "lgcyX2", "probabilistic_switching", mode="probe")
    assert ResolvedRun.from_json(run.to_json()) == run
    as_yaml = yaml.safe_dump(run.model_dump(mode="json"))
    assert ResolvedRun.model_validate(yaml.safe_load(as_yaml)) == run


def test_hash_is_stable_across_checkouts(tmp_path):
    shutil.copytree(TREE, tmp_path / "one")
    shutil.copytree(TREE, tmp_path / "two" / "nested")
    one = load_config(tmp_path / "one", source=RunSource(revision="r1"))
    two = load_config(tmp_path / "two" / "nested", source=RunSource(kind="git"))
    a = run_of(one, "alfa", "lgcyX1", "sequence", run_id="run-1")
    b = run_of(two, "alfa", "lgcyX1", "sequence", run_id="run-2")
    assert a.payload_sha256 == b.payload_sha256
    exclude = {"source", "run_id"}
    assert a.model_dump(exclude=exclude) == b.model_dump(exclude=exclude)


def test_hash_follows_content(config):
    run = run_of(config, "alfa", "lgcyX1", "sequence")
    other = run_of(
        config,
        "alfa",
        "lgcyX1",
        "sequence",
        run_overrides={"barcode": {"bits": 21}},
    )
    assert run.payload_sha256 != other.payload_sha256
    tampered = json.loads(run.to_json())
    tampered["settings"]["barcode"]["bits"] = 21
    with pytest.raises(ContentHashError):
        ResolvedRun.from_json(json.dumps(tampered))
    assert ResolvedRun.from_json(json.dumps(tampered), verify=False).settings


def test_payload_refuses_other_schema_version(config):
    data = json.loads(run_of(config, "alfa", "lgcyX1", "sequence").to_json())
    data["schema_version"] = 2
    with pytest.raises(SchemaVersionError):
        ResolvedRun.from_json(json.dumps(data))


def test_null_inherits_the_level_below(config):
    run = run_of(
        config,
        "setup-1",
        "lgcyX2",
        "probabilistic_switching",
        run_overrides={"barcode": {"bit_duration_ms": None}, "new_key": None},
    )
    levels = settings_levels(run)
    assert levels["/barcode/bit_duration_ms"] == (100.0, "setup")
    assert levels["/new_key"] == (None, "run")


def test_source_id_prefixes_provenance_and_packages_are_recorded():
    loaded = load_config(TREE, source=RunSource(kind="git", id="configs"))
    run = run_of(
        loaded,
        "alfa",
        "lgcyX1",
        "sequence",
        package_versions={"task-package": "1.2.3"},
    )
    src = run.provenance["/settings/calibration_policy/stale_days"]
    assert src.file == "configs:setups/alfa.yaml"
    assert run.packages == {"task-package": "1.2.3"}
    assert run.source.kind == "git"


def test_hash_ignores_file_layout():
    merged = {}
    for path in sorted(TREE.glob("*/*.yaml")):
        if path.parent.name in ("machines", "setups", "tasks", "subjects"):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            for section, body in data.items():
                if section != "schema_version":
                    merged.setdefault(section, {}).update(body)
    one_file = merge_fragments([("all.yaml", {"schema_version": 3, **merged})])
    split = load_config(TREE)
    a = run_of(split, "alfa", "lgcyX1", "sequence")
    b = run_of(one_file, "alfa", "lgcyX1", "sequence")
    assert a.provenance != b.provenance
    assert a.payload_sha256 == b.payload_sha256


def test_box_role_resolves_only_from_boxes(config):
    doc = config.document.model_copy(deep=True)
    doc.setups["alfa"].uses["box"] = "bpod-a"
    with pytest.raises(UnknownNameError, match="no box of that name"):
        resolve(doc, "alfa", "lgcyX1", "sequence")
    doc.setups["alfa"].uses["box"] = "kappa"
    doc.setups["alfa"].uses["bpod"] = "kappa"
    with pytest.raises(UnknownNameError, match="no device of that name"):
        resolve(doc, "alfa", "lgcyX1", "sequence")
