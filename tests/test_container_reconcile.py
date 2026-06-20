"""Container enumeration + manifest reconciliation (backcompat for old manifests).

Disk is the source of truth; the manifest is an overlay. These tests build
synthetic containers (behaviour + camera acquisition dirs, with manifests that
are complete, incomplete, or absent) and check that enumeration unions disk and
manifest and that validation surfaces the mismatches.
"""

from __future__ import annotations

import yaml

from murineshiftwork.readers import (
    enumerate_acquisitions,
    load_acquisition,
    validate_session_container,
)

_DT = "20260620_120000_000000"
_BEHAV = f"s1__{_DT}__sequence__v1"
_FLIR = f"s1__{_DT}__video_flir__v1"


def _mk_acq_dir(container, basename):
    d = container / basename
    d.mkdir()
    return d


def _write_manifest(container, basenames):
    (container / "session_manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "msw_manifest_version": 1,
                "type": "session",
                "acquisitions": [
                    {"basename": b, "status": "complete"} for b in basenames
                ],
            }
        )
    )


def test_enumerate_unions_disk_and_manifest(tmp_path):
    # behaviour + camera on disk, but manifest lists only the behaviour one
    _mk_acq_dir(tmp_path, _BEHAV)
    _mk_acq_dir(tmp_path, _FLIR)
    _write_manifest(tmp_path, [_BEHAV])

    infos = {i.basename: i for i in enumerate_acquisitions(tmp_path)}
    assert set(infos) == {_BEHAV, _FLIR}

    assert infos[_BEHAV].kind == "behaviour"
    assert infos[_BEHAV].in_manifest is True

    # the camera acquisition is found on disk despite being unregistered
    assert infos[_FLIR].kind == "camera"
    assert infos[_FLIR].backend == "flir"
    assert infos[_FLIR].on_disk is True
    assert infos[_FLIR].in_manifest is False


def test_validate_flags_unregistered_acquisition(tmp_path):
    _mk_acq_dir(tmp_path, _BEHAV)
    _mk_acq_dir(tmp_path, _FLIR)
    _write_manifest(tmp_path, [_BEHAV])  # camera missing from manifest

    report = validate_session_container(tmp_path)
    assert report.on_disk_not_in_manifest == [_FLIR]
    assert report.in_manifest_not_on_disk == []
    assert report.is_consistent is False


def test_validate_flags_dangling_manifest_entry(tmp_path):
    _mk_acq_dir(tmp_path, _BEHAV)
    _write_manifest(tmp_path, [_BEHAV, _FLIR])  # camera listed but not on disk

    report = validate_session_container(tmp_path)
    assert report.in_manifest_not_on_disk == [_FLIR]
    assert report.on_disk_not_in_manifest == []
    assert report.is_consistent is False


def test_validate_consistent_when_manifest_matches_disk(tmp_path):
    _mk_acq_dir(tmp_path, _BEHAV)
    _mk_acq_dir(tmp_path, _FLIR)
    _write_manifest(tmp_path, [_BEHAV, _FLIR])

    report = validate_session_container(tmp_path)
    assert report.is_consistent is True


def test_enumerate_works_without_manifest(tmp_path):
    _mk_acq_dir(tmp_path, _BEHAV)
    _mk_acq_dir(tmp_path, _FLIR)
    # no manifest written at all (oldest case)
    infos = {i.basename: i for i in enumerate_acquisitions(tmp_path)}
    assert set(infos) == {_BEHAV, _FLIR}
    assert all(i.in_manifest is False for i in infos.values())


def test_load_acquisition_skips_camera_dirs(tmp_path):
    # load_acquisition returns behavioural MswSessions only; camera dirs are
    # not mis-loaded as empty sessions even when unregistered on disk.
    _mk_acq_dir(tmp_path, _FLIR)
    _write_manifest(tmp_path, [])
    sessions = load_acquisition(tmp_path)
    assert all("video_flir" not in s.acquisition_name for s in sessions if s)
    # only a camera dir present -> no behavioural sessions
    assert sessions == []


def test_load_acquisition_skips_unknown_dirs(tmp_path):
    # a __-named dir with no recognised MSW files is not an acquisition: it is
    # skipped (not attempted, no error), while a real one alongside still loads.
    _mk_acq_dir(tmp_path, _BEHAV)  # empty: no recognised files
    (tmp_path / "stray__not__an__acq").mkdir()
    sessions = load_acquisition(tmp_path)
    assert sessions == []  # neither dir holds recognised files


def test_enumerate_classifies_legacy_dir_with_files_as_behaviour(tmp_path):
    # a dir whose name does not parse but which holds a recognised (legacy)
    # file is a behavioural acquisition, not unknown.
    legacy = tmp_path / "mouse_2024_session_01"
    legacy.mkdir()
    (legacy / "switching.pkl").write_bytes(b"\x00")  # legacy marker
    infos = {i.basename: i for i in enumerate_acquisitions(tmp_path)}
    assert infos["mouse_2024_session_01"].kind == "behaviour"
    assert infos["mouse_2024_session_01"].acq_type == ""


def test_enumerate_marks_empty_dir_unknown(tmp_path):
    stray = tmp_path / "stray__dir"
    stray.mkdir()  # no recognised files, does not parse
    infos = {i.basename: i for i in enumerate_acquisitions(tmp_path)}
    assert infos["stray__dir"].kind == "unknown"
