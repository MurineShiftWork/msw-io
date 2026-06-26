"""Unit tests for murineshiftwork.namespace.

All tests use dummy scalar arguments: no CLI, no hardware, no config files.
"""

from datetime import datetime

import pytest

from murineshiftwork.namespace.paths import (
    _NAMESPACE_FORMATS,
    CURRENT_NAMESPACE_VERSION,
    NAMESPACE_LEGACY,
    NAMESPACE_V1,
    build_data_paths,
    generate_session_paths,
    make_subject,
    parse_acquisition_basename,
    parse_session_basename,
    parse_subject,
)


@pytest.mark.parametrize(
    "tail,exp_acq,exp_task,exp_ver,exp_legacy",
    [
        # v4.3: acq_type enum + optional task token (+ legacy __vN)
        ("msw__sequence", "msw", "sequence", None, False),
        ("msw__sequence__v1", "msw", "sequence", 1, False),
        ("msw", "msw", None, None, False),
        ("video_flir", "video_flir", None, None, False),
        ("pxi__v2", "pxi", None, 2, False),
        # legacy: task in the acq_type slot -> acq system is implicitly msw
        ("sequence", "msw", "sequence", None, True),
        ("sequence__v1", "msw", "sequence", 1, True),
    ],
)
def test_parse_acquisition_v43_grammar(tail, exp_acq, exp_task, exp_ver, exp_legacy):
    info = parse_acquisition_basename(f"_test_subject__20260619_120000_000000__{tail}")
    assert info["subject"] == "_test_subject"
    assert info["acq_type"] == exp_acq
    assert info["task"] == exp_task
    assert info["acq_version"] == exp_ver
    assert info["is_legacy_acquisition"] is exp_legacy


def test_emitter_task_token_only_for_msw():
    """v4.3: the task token is emitted into the path for the behaviour acq system
    (acq_type 'msw') only; typed acquisitions never carry it (no leak to camera/
    ephys consumers), even when a task is passed."""
    msw = generate_session_paths(
        "m1", "sequence", "/data", acq_type="msw", acq_version=None, printout=False
    )
    assert "__msw__sequence" in msw["session_basename"]
    # round-trips back to acq_type=msw, task=sequence
    back = parse_acquisition_basename(msw["session_basename"])
    assert back["acq_type"] == "msw" and back["task"] == "sequence"

    for at in ("video_flir", "video_rce", "pxi", "photo"):
        bn = generate_session_paths(
            "m1", "sequence", "/data", acq_type=at, acq_version=None, printout=False
        )["session_basename"]
        assert bn.endswith(at)  # path ends at acq_type: no task tag handed down
        assert "sequence" not in bn


# ---------------------------------------------------------------------------
# Version constants


def test_current_version_is_v1():
    assert CURRENT_NAMESPACE_VERSION == NAMESPACE_V1


def test_v1_format_has_microseconds():
    assert "%f" in _NAMESPACE_FORMATS[NAMESPACE_V1]


def test_legacy_format_has_no_microseconds():
    assert "%f" not in _NAMESPACE_FORMATS[NAMESPACE_LEGACY]


# ---------------------------------------------------------------------------
# generate_session_paths: v1


def test_v1_basename_structure():
    paths = generate_session_paths(
        "mouse_01", "flush", "/data", version=NAMESPACE_V1, printout=False
    )
    parts = paths["session_basename"].split("__")
    # v4.3: subject__datetime__acq_type__task__vN (msw behaviour acq carries task)
    assert len(parts) == 5
    assert parts[0] == "mouse_01"
    assert parts[2] == "msw"  # acq_type (system), task visible next
    assert parts[3] == "flush"  # task token
    assert parts[4] == "v1"


def test_v1_datetime_has_microseconds():
    paths = generate_session_paths(
        "mouse_01", "flush", "/data", version=NAMESPACE_V1, printout=False
    )
    dt_str = paths["session_basename"].split("__")[1]
    # v1 format: YYYYmmdd_HHMMSS_ffffff  → 22 chars
    assert len(dt_str) == 22
    dt = datetime.strptime(dt_str, _NAMESPACE_FORMATS[NAMESPACE_V1])
    assert isinstance(dt, datetime)


def test_v1_namespace_version_in_result():
    paths = generate_session_paths(
        "mouse_01", "flush", "/data", version=NAMESPACE_V1, printout=False
    )
    assert paths["namespace_version"] == NAMESPACE_V1


def test_v1_session_folder_path():
    paths = generate_session_paths(
        "mouse_01", "flush", "/data", version=NAMESPACE_V1, printout=False
    )
    assert paths["session_folder"].startswith("/data/mouse_01/")
    assert "mouse_01__" in paths["session_folder"]
    assert "__msw" in paths["session_folder"]  # acq_type suffix in folder


def test_v1_standalone_acquisition_name():
    # Standalone: session container is subject__datetime (no task/type suffix).
    paths = generate_session_paths(
        "mouse_01", "flush", "/data", version=NAMESPACE_V1, printout=False
    )
    assert paths["host_session_name"] is not None
    # v4: container is just subject__datetime, no task embedded
    assert "session_flush" not in paths["host_session_name"]
    assert paths["acquisition_name"] == paths["session_basename"]
    assert paths["session_folder"].startswith(
        f"/data/mouse_01/{paths['host_session_name']}/"
    )


def test_v1_child_session_nesting():
    # linked_to becomes the host session container; acquisition is nested inside it.
    parent = "mouse_01__20260514_143022_123456__parent_task"
    paths = generate_session_paths(
        "mouse_01",
        "child_task",
        "/data",
        version=NAMESPACE_V1,
        linked_to=parent,
        printout=False,
    )
    assert paths["host_session_name"] == parent
    assert paths["acquisition_name"] == paths["session_basename"]
    # MSW acquisition folder is nested inside the host session dir
    assert f"/{parent}/" in paths["session_folder"]
    assert paths["session_folder"].startswith(f"/data/mouse_01/{parent}/")


def test_sibling_acquisition_shares_datetime_via_datetime_str():
    # To create a sibling acquisition (e.g. video_flir), the caller passes
    # session_paths["datetime"] from the primary acquisition. No string splitting
    # anywhere - the datetime comes from the builder's own output dict.
    msw_paths = generate_session_paths(
        "mouse_01", "task", "/data", version=NAMESPACE_V1, printout=False
    )
    video_paths = generate_session_paths(
        "mouse_01",
        "task",
        "/data",
        acq_type="video_flir",
        version=NAMESPACE_V1,
        linked_to=msw_paths["host_session_name"],
        datetime_str=msw_paths["datetime"],
        printout=False,
    )
    assert video_paths["datetime"] == msw_paths["datetime"]
    assert video_paths["host_session_name"] == msw_paths["host_session_name"]
    # video_flir is a sibling acquisition and also carries the default version.
    expected = f"mouse_01__{msw_paths['datetime']}__video_flir__v1"
    assert video_paths["session_basename"] == expected


# ---------------------------------------------------------------------------
# generate_session_paths: legacy


def test_legacy_datetime_seconds_only():
    paths = generate_session_paths(
        "mouse_01", "flush", "/data", version=NAMESPACE_LEGACY, printout=False
    )
    dt_str = paths["session_basename"].split("__")[1]
    # legacy format: YYYYmmdd_HHMMSS  → 15 chars
    assert len(dt_str) == 15
    dt = datetime.strptime(dt_str, _NAMESPACE_FORMATS[NAMESPACE_LEGACY])
    assert isinstance(dt, datetime)


def test_legacy_namespace_version_in_result():
    paths = generate_session_paths(
        "mouse_01", "flush", "/data", version=NAMESPACE_LEGACY, printout=False
    )
    assert paths["namespace_version"] == NAMESPACE_LEGACY


# ---------------------------------------------------------------------------
# generate_session_paths: validation


def test_unknown_version_raises():
    with pytest.raises(ValueError, match="Unknown namespace version"):
        generate_session_paths(
            "mouse_01", "flush", "/data", version="v99", printout=False
        )


def test_forbidden_chars_in_subject_raise():
    for bad_char in [" ", "#", "@", "!"]:
        with pytest.raises(ValueError, match="forbidden characters"):
            generate_session_paths(
                f"mouse{bad_char}01", "flush", "/data", printout=False
            )


def test_test_task_uses_default_subject():
    paths = generate_session_paths(
        "real_subject",
        "_test__flush",
        "/data",
        version=NAMESPACE_V1,
        printout=False,
    )
    assert paths["subject"] == "_test_subject"


# ---------------------------------------------------------------------------
# build_data_paths: shim


def test_build_data_paths_uses_current_version():
    paths = build_data_paths(
        basepath="/data", subject="mouse_01", task="flush", printout=False
    )
    assert paths["namespace_version"] == CURRENT_NAMESPACE_VERSION


def test_build_data_paths_output_equivalent_to_generate():
    """build_data_paths and generate_session_paths(version=CURRENT) have the same keys."""
    a = build_data_paths(
        basepath="/data", subject="mouse_01", task="flush", printout=False
    )
    b = generate_session_paths("mouse_01", "flush", "/data", printout=False)
    assert set(a.keys()) == set(b.keys())


# ---------------------------------------------------------------------------
# parse_session_basename: version detection


def test_parse_v1_basename():
    basename = "mouse_01__20260514_143022_123456__sequence_automated"
    info = parse_session_basename(basename)
    assert info["namespace_version"] == NAMESPACE_V1
    assert info["subject"] == "mouse_01"
    assert info["task"] == "sequence_automated"
    assert info["datetime"].microsecond == 123456
    assert info["datetime_str"] == "20260514_143022_123456"


def test_parse_legacy_basename():
    basename = "sleep_lhb_c344986_m1097354__20210718_152153__probabilistic_switching"
    info = parse_session_basename(basename)
    assert info["namespace_version"] == NAMESPACE_LEGACY
    assert info["subject"] == "sleep_lhb_c344986_m1097354"
    assert info["task"] == "probabilistic_switching"
    assert info["datetime"].microsecond == 0
    assert info["datetime"].year == 2021


def test_parse_roundtrip_v1():
    """Basename generated by v1 must parse back as v1; v4.3 msw acq carries task."""
    paths = generate_session_paths(
        "mouse_01", "flush", "/data", version=NAMESPACE_V1, printout=False
    )
    info = parse_session_basename(paths["session_basename"])
    assert info["namespace_version"] == NAMESPACE_V1
    assert info["subject"] == "mouse_01"
    # v4.3: the msw behaviour acquisition carries the task token
    assert info["task"] == "flush"


def test_parse_roundtrip_legacy():
    paths = generate_session_paths(
        "mouse_01", "flush", "/data", version=NAMESPACE_LEGACY, printout=False
    )
    info = parse_session_basename(paths["session_basename"])
    assert info["namespace_version"] == NAMESPACE_LEGACY


def test_parse_wrong_separator_count_raises():
    with pytest.raises(ValueError):
        parse_session_basename("bad_name_no_separators")


def test_parse_bad_datetime_raises():
    # "notadatetime" fails the session regex (no \d{8}_\d{6} match), so the
    # builder catches it before the version-detection loop.
    with pytest.raises(ValueError):
        parse_session_basename("mouse_01__notadatetime__flush")


# ---------------------------------------------------------------------------
# parse_subject / make_subject (v4.1 structured subject)


@pytest.mark.parametrize(
    "subject, expected",
    [
        (
            "t004_m2045",
            {"subject_id": "t004", "animal_id": "m2045", "tag_id": None, "fields": []},
        ),
        (
            "s001_m1234",
            {"subject_id": "s001", "animal_id": "m1234", "tag_id": None, "fields": []},
        ),
        (
            "seq001_m0567_4A7B",
            {
                "subject_id": "seq001",
                "animal_id": "m0567",
                "tag_id": "4A7B",
                "fields": ["4A7B"],
            },
        ),
        (
            "t004_m2045_LR3",
            {
                "subject_id": "t004",
                "animal_id": "m2045",
                "tag_id": "LR3",
                "fields": ["LR3"],
            },
        ),
        # Legacy 4-part subject (tag + extra metadata token)
        (
            "t004_m2045_LR3_batch2",
            {
                "subject_id": "t004",
                "animal_id": "m2045",
                "tag_id": "LR3",
                "fields": ["LR3", "batch2"],
            },
        ),
        # Legacy 5-part subject
        (
            "seq001_r012_4A7B_spindle_wk3",
            {
                "subject_id": "seq001",
                "animal_id": "r012",
                "tag_id": "4A7B",
                "fields": ["4A7B", "spindle", "wk3"],
            },
        ),
    ],
)
def test_parse_subject_valid(subject, expected):
    assert parse_subject(subject) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "t004",  # missing animal_id
        "mouse001",  # no underscore separator for animal_id
        "004_m2045",  # subject_id must start with letters
        "t004_2045",  # animal_id must start with a letter
        "t004_mm2045",  # animal_id must start with single letter
        "_m2045",  # empty subject_id
        "t004_",  # incomplete
        "",  # empty
    ],
)
def test_parse_subject_invalid(bad):
    with pytest.raises(ValueError):
        parse_subject(bad)


def test_make_subject_two_parts():
    assert make_subject("t004", "m2045") == "t004_m2045"


def test_make_subject_three_parts():
    assert make_subject("t004", "m2045", "4A7B") == "t004_m2045_4A7B"


def test_make_subject_four_parts():
    assert make_subject("t004", "m2045", "LR3", "batch2") == "t004_m2045_LR3_batch2"


def test_make_subject_invalid_subject_id_raises():
    with pytest.raises(ValueError):
        make_subject("004", "m2045")


def test_make_subject_invalid_animal_id_raises():
    with pytest.raises(ValueError):
        make_subject("t004", "2045")


def test_make_subject_roundtrip():
    s = make_subject("seq001", "r012", "LR3")
    parts = parse_subject(s)
    assert parts["subject_id"] == "seq001"
    assert parts["animal_id"] == "r012"
    assert parts["tag_id"] == "LR3"
    assert parts["fields"] == ["LR3"]


def test_parse_subject_fields_independent_of_tag_id():
    """fields list always contains all extra tokens; tag_id is fields[0]."""
    result = parse_subject("t004_m2045_A1_B2_C3")
    assert result["fields"] == ["A1", "B2", "C3"]
    assert result["tag_id"] == "A1"
