"""Tests for namespace.msw.yaml, msw_files, paths, and TaskRunner.get_path()."""

from pathlib import Path

import pytest

_NAMESPACE_DIR = Path(__file__).parent.parent / "src" / "murineshiftwork" / "namespace"

# v4 acquisition basename: subject__datetime__acq_type
_BASE = "/data/mouse_01/mouse_01__20260524_143022_123456/mouse_01__20260524_143022_123456__msw/mouse_01__20260524_143022_123456__msw"


# ---------------------------------------------------------------------------
# namespace.msw.yaml loads correctly


def test_msw_yaml_loads():
    from acquisition_namespace import NamespaceBuilder

    b = NamespaceBuilder.from_yaml(_NAMESPACE_DIR / "namespace.msw.yaml")
    assert b.spec.version == "4.2"
    assert b.hierarchy == ["subject", "session", "acquisition", "file"]
    assert "acquisition" not in b.optional_levels


def test_msw_yaml_loads_correctly():
    from acquisition_namespace import NamespaceBuilder

    p = _NAMESPACE_DIR / "namespace.msw.yaml"
    assert p.exists(), f"Missing: {p}"
    b = NamespaceBuilder.from_yaml(p)
    assert b.hierarchy == ["subject", "session", "acquisition", "file"]


# ---------------------------------------------------------------------------
# get_msw_builder(): lazy singleton


def test_get_msw_builder_returns_builder():
    from murineshiftwork.namespace.paths import get_msw_builder

    b = get_msw_builder()
    assert b.hierarchy == ["subject", "session", "acquisition", "file"]
    assert "acquisition" not in b.optional_levels


def test_get_msw_builder_is_cached():
    from murineshiftwork.namespace.paths import get_msw_builder

    assert get_msw_builder() is get_msw_builder()


# ---------------------------------------------------------------------------
# build_path("file", ...) round-trip


@pytest.mark.parametrize(
    "artifact",
    ["session.yaml", "df.jsonl", "log", "jsonl", "plot_spec.yaml", "stimulation.json"],
)
def test_build_file_path_roundtrip(artifact):
    from murineshiftwork.namespace.paths import get_msw_builder

    b = get_msw_builder()
    values = {
        "subject": "mouse_01",
        "datetime": "20260524_143022_123456",
        "acq_type": "msw",
        "artifact": artifact,
    }
    fname = b.build_path("file", values)
    assert fname == f"mouse_01__20260524_143022_123456__msw.msw.{artifact}"

    extracted = b.extract_level_values("file", fname)
    assert extracted["artifact"] == artifact
    assert extracted["acquisition"] == "mouse_01__20260524_143022_123456__msw"


@pytest.mark.parametrize(
    ("name", "acq_type", "version"),
    [
        ("m01__20260524_143022_123456__sequence__v1", "sequence", "1"),
        ("m01__20260524_143022_123456__sequence", "sequence", None),
        ("m01__20260524_143022_123456__video_flir__v2", "video_flir", "2"),
        ("m01__20260524_143022_123456__video_flir", "video_flir", None),
        (
            "_t__20260524_143022_123456___test_minimal_task__v1",
            "_test_minimal_task",
            "1",
        ),
    ],
)
def test_acquisition_regex_splits_optional_version(name, acq_type, version):
    # acq_type is lazy + end-anchored so a trailing __v{n} is not swallowed
    # (\w includes underscore). Both versioned and unversioned names parse.
    from murineshiftwork.namespace.paths import get_msw_builder

    v = get_msw_builder().extract_level_values("acquisition", name)
    assert v["acq_type"] == acq_type
    assert v.get("version") == version


def test_build_file_legacy_datetime():
    from murineshiftwork.namespace.paths import get_msw_builder

    b = get_msw_builder()
    fname = b.build_path(
        "file",
        {
            "subject": "mouse_01",
            "datetime": "20210718_152153",
            "acq_type": "msw",
            "artifact": "session.yaml",
        },
    )
    assert fname == "mouse_01__20210718_152153__msw.msw.session.yaml"


# ---------------------------------------------------------------------------
# parse_acquisition_basename()


def test_parse_acquisition_v4_msw():
    from murineshiftwork.namespace.paths import parse_acquisition_basename

    info = parse_acquisition_basename("mouse_01__20260524_143022_123456__msw")
    assert info["subject"] == "mouse_01"
    assert info["acq_type"] == "msw"
    assert info["acq_version"] is None
    assert info["is_legacy_acquisition"] is False


def test_parse_acquisition_v4_with_version():
    from murineshiftwork.namespace.paths import parse_acquisition_basename

    info = parse_acquisition_basename("mouse_01__20260524_143022_123456__msw__v2")
    assert info["acq_type"] == "msw"
    assert info["acq_version"] == 2
    assert info["is_legacy_acquisition"] is False


def test_parse_acquisition_v4_pxi():
    from murineshiftwork.namespace.paths import parse_acquisition_basename

    info = parse_acquisition_basename("mouse_01__20260524_143022_123456__pxi")
    assert info["acq_type"] == "pxi"
    assert info["acq_version"] is None


def test_parse_acquisition_legacy_task_name():
    from murineshiftwork.namespace.paths import parse_acquisition_basename

    info = parse_acquisition_basename(
        "mouse_01__20260524_143022_123456__probabilistic_switching"
    )
    assert info["acq_type"] == "msw"
    assert info["task"] == "probabilistic_switching"
    assert info["is_legacy_acquisition"] is True


def test_parse_acquisition_legacy_second_precision():
    from murineshiftwork.namespace.paths import parse_acquisition_basename

    info = parse_acquisition_basename("mouse_01__20210718_152153__sequence")
    assert info["subject"] == "mouse_01"
    assert info["namespace_version"] == "legacy"
    assert info["is_legacy_acquisition"] is True


# ---------------------------------------------------------------------------
# generate_session_paths()


def test_generate_session_paths_v4_structure(tmp_path):
    from murineshiftwork.namespace.paths import generate_session_paths

    paths = generate_session_paths(
        subject="mouse_01",
        task="probabilistic_switching",
        basepath=tmp_path,
        acq_type="msw",
        printout=False,
    )
    assert paths["acq_type"] == "msw"
    assert paths["acq_version"] == 1  # version written by default
    assert "mouse_01" in paths["session_folder"]
    assert paths["session_basename"].endswith("__msw__v1")
    assert "__" not in paths["subject"]


def test_generate_session_paths_no_version_when_explicit_none(tmp_path):
    from murineshiftwork.namespace.paths import generate_session_paths

    # External/unversioned acquisition types pass acq_version=None to opt out.
    paths = generate_session_paths(
        subject="mouse_01",
        task="t",
        basepath=tmp_path,
        acq_type="pxi",
        acq_version=None,
        printout=False,
    )
    assert paths["session_basename"].endswith("__pxi")
    assert not paths["session_basename"].endswith("__v1")


def test_generate_session_paths_with_version(tmp_path):
    from murineshiftwork.namespace.paths import generate_session_paths

    paths = generate_session_paths(
        subject="mouse_01",
        task="seq",
        basepath=tmp_path,
        acq_type="msw",
        acq_version=2,
        printout=False,
    )
    assert paths["session_basename"].endswith("__v2")


def test_generate_session_paths_session_type(tmp_path):
    from murineshiftwork.namespace.paths import generate_session_paths

    paths = generate_session_paths(
        subject="mouse_01",
        task="seq",
        basepath=tmp_path,
        session_type="ephys",
        printout=False,
    )
    assert "ephys" in paths["host_session_name"]


def test_generate_session_paths_session_type_with_version(tmp_path):
    from murineshiftwork.namespace.paths import generate_session_paths

    paths = generate_session_paths(
        subject="mouse_01",
        task="seq",
        basepath=tmp_path,
        session_type="sequence",
        acq_version=1,
        printout=False,
    )
    # version is at acquisition level only; session container has no _vN
    assert paths["host_session_name"].endswith("__sequence")
    assert "_v1" not in paths["host_session_name"]
    assert paths["session_basename"].endswith("__v1")


def test_generate_session_paths_session_type_without_version(tmp_path):
    from murineshiftwork.namespace.paths import generate_session_paths

    paths = generate_session_paths(
        subject="mouse_01",
        task="seq",
        basepath=tmp_path,
        session_type="sequence",
        printout=False,
    )
    assert "__sequence" in paths["host_session_name"]
    assert not paths["host_session_name"].endswith("_v")


def test_generate_session_paths_rejects_double_underscore(tmp_path):
    from murineshiftwork.namespace.paths import generate_session_paths

    with pytest.raises(ValueError, match="double-underscore"):
        generate_session_paths(
            subject="bad__subject",
            task="seq",
            basepath=tmp_path,
            printout=False,
        )


# ---------------------------------------------------------------------------
# msw_file()


def test_msw_file_produces_correct_path():
    from murineshiftwork.namespace import msw_file

    p = msw_file(_BASE, "session.yaml")
    assert p.as_posix() == _BASE + ".msw.session.yaml"
    assert isinstance(p, Path)


def test_msw_file_df_jsonl():
    from murineshiftwork.namespace import msw_file

    p = msw_file(_BASE, "df.jsonl")
    assert p.as_posix() == _BASE + ".msw.df.jsonl"


def test_msw_file_accepts_path_object():
    from murineshiftwork.namespace import msw_file

    p = msw_file(Path(_BASE), "log")
    assert p.as_posix() == _BASE + ".msw.log"


# ---------------------------------------------------------------------------
# is_msw_file()


def test_is_msw_file_true_for_session_yaml():
    from murineshiftwork.namespace import is_msw_file

    assert is_msw_file(_BASE + ".msw.session.yaml")


def test_is_msw_file_true_for_df_jsonl():
    from murineshiftwork.namespace import is_msw_file

    assert is_msw_file(_BASE + ".msw.df.jsonl")


def test_is_msw_file_false_for_plain_csv():
    from murineshiftwork.namespace import is_msw_file

    assert not is_msw_file("/data/subject/session/something.csv")


def test_is_msw_file_false_for_no_separator():
    from murineshiftwork.namespace import is_msw_file

    assert not is_msw_file("subject__20260524_143022_123456__msw.jsonl")


# ---------------------------------------------------------------------------
# msw_artifact()


def test_msw_artifact_session_yaml():
    from murineshiftwork.namespace import msw_artifact

    assert msw_artifact(_BASE + ".msw.session.yaml") == "session.yaml"


def test_msw_artifact_df_jsonl():
    from murineshiftwork.namespace import msw_artifact

    assert msw_artifact(_BASE + ".msw.df.jsonl") == "df.jsonl"


def test_msw_artifact_raises_for_non_msw():
    from murineshiftwork.namespace import msw_artifact

    with pytest.raises(ValueError, match="Not an MSW file"):
        msw_artifact("/data/something.csv")
