"""Tests for murineshiftwork.readers.session: _PermissiveLoader and read_session_data."""

from __future__ import annotations

import pytest
import yaml

# ---------------------------------------------------------------------------
# _PermissiveLoader: historical YAML read tolerance

_PYTHON_NAME_YAML = """\
msw_format_version: 2
process:
  task: optotagging
task_settings:
  n_trials: 10
  valve_s_for_ul: !!python/name:murineshiftwork.cli.evaluate.%3Clambda%3E ''
  other_key: hello
"""


def test_safe_load_raises_on_python_name_tag():
    """Confirm baseline: SafeLoader raises on !!python/name: so the
    permissive loader is actually needed."""
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.safe_load(_PYTHON_NAME_YAML)


def test_permissive_loader_does_not_raise():
    from murineshiftwork.readers.session import _PermissiveLoader

    data = yaml.load(_PYTHON_NAME_YAML, Loader=_PermissiveLoader)
    assert isinstance(data, dict)


def test_permissive_loader_maps_python_name_to_none():
    from murineshiftwork.readers.session import _PermissiveLoader

    data = yaml.load(_PYTHON_NAME_YAML, Loader=_PermissiveLoader)
    assert data["task_settings"]["valve_s_for_ul"] is None


def test_permissive_loader_preserves_other_keys():
    from murineshiftwork.readers.session import _PermissiveLoader

    data = yaml.load(_PYTHON_NAME_YAML, Loader=_PermissiveLoader)
    assert data["task_settings"]["other_key"] == "hello"
    assert data["task_settings"]["n_trials"] == 10
    assert data["process"]["task"] == "optotagging"


def test_permissive_loader_safe_for_normal_yaml():
    from murineshiftwork.readers.session import _PermissiveLoader

    normal = "msw_format_version: 2\nprocess:\n  task: sequence\n"
    data = yaml.load(normal, Loader=_PermissiveLoader)
    assert data == yaml.safe_load(normal)


# ---------------------------------------------------------------------------
# End-to-end: session with !!python/name: tag is loaded by the reader


def test_reader_loads_session_yaml_with_python_name_tag(tmp_path):
    from murineshiftwork.readers import load_session

    session_basename = "_test_subject__20260101_120000_000001__optotagging"
    session_dir = tmp_path / session_basename
    session_dir.mkdir()

    session_yaml = session_dir / f"{session_basename}.msw.session.yaml"
    session_yaml.write_text(_PYTHON_NAME_YAML)

    s = load_session(session_dir)
    assert s.task == "optotagging"
    ts = s.settings_task or {}
    assert ts.get("valve_s_for_ul") is None
    assert ts.get("other_key") == "hello"
