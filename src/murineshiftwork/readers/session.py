"""Low-level session reader: format detection and artifact loading.

Dispatches to one of three format readers based on what files are present:
- ``session_yaml``: single ``.msw.session.yaml`` (current format, v2+)
- ``separate_json``: separate ``.msw.settings.*.json`` + trial data file
- ``legacy``: ``task_settings.py`` + ``switching.pkl/csv``
"""

import logging
from pathlib import Path

import pandas as pd
import yaml

from murineshiftwork.readers.files import read_json, read_settings_py, read_trial_df
from murineshiftwork.readers.namespace import (
    ARTIFACT_FORMAT_LEGACY,
    ARTIFACT_FORMAT_SEPARATE_JSON,
    ARTIFACT_FORMAT_SESSION_YAML,
    detect_session_format,
    test_is_legacy_format,
    test_is_recognized_msw_file,
)


class _PermissiveLoader(yaml.SafeLoader):
    """SafeLoader that drops unresolvable PyYAML Python tags.

    Historical session YAMLs may contain serialised callables (e.g.
    valve_s_for_ul as !!python/object/apply:builtins.getattr or
    !!python/name:) written by PyYAML's default Dumper. SafeLoader raises
    on those; this loader silently drops them so old files remain readable.
    """


_PermissiveLoader.add_multi_constructor(
    "tag:yaml.org,2002:python/name:",
    lambda loader, tag_suffix, node: None,
)
_PermissiveLoader.add_multi_constructor(
    "tag:yaml.org,2002:python/object/apply:",
    lambda loader, tag_suffix, node: None,
)
_PermissiveLoader.add_multi_constructor(
    "tag:yaml.org,2002:python/object:",
    lambda loader, tag_suffix, node: None,
)


def _normalize_host_block(block: dict) -> dict:
    """Canonicalize the host/ephys block to current field names."""
    out = dict(block)
    if "acquisition_name" in out:
        if "session_name" not in out:
            out["session_name"] = out["acquisition_name"]
        del out["acquisition_name"]
    return out


def _msw_files_dict(session_dir: Path) -> dict[str, str]:
    """Return {artifact_key: filepath} for all recognised MSW files in session_dir."""
    files = [str(p) for p in session_dir.glob("*")]

    def _key(s: str) -> str:
        return s.split(".msw.")[-1].replace("msw", "").strip(".")

    return {_key(v): v for v in files if test_is_recognized_msw_file(v)}


def _attach_msw_version(data: dict, is_legacy: bool) -> None:
    proc = data.get("settings.process", {}) or {}
    if "msw_version" in proc:
        data["msw_version"] = proc["msw_version"]
    elif is_legacy:
        data["msw_version"] = "legacy"
    else:
        data["msw_version"] = "< 1.0.0"


def _check_completeness(data: dict, is_legacy: bool) -> bool:
    required = ["df", "settings.task"]
    if not is_legacy:
        required.append("settings.process")
    for k in required:
        if k not in data:
            return False
    return data.get("df") is not None


def _read_session_yaml(session_dir: Path, fmt: dict) -> dict:
    """ARTIFACT_FORMAT_SESSION_YAML: single .msw.session.yaml (v2+)."""
    files = _msw_files_dict(session_dir)
    data: dict = {}

    for k, v in files.items():
        if k == "session.yaml" and ".msw." in v:
            payload = yaml.load(Path(v).read_text(), Loader=_PermissiveLoader) or {}
            if payload.get("msw_format_version", 1) >= 2:
                if "process" in payload:
                    data["settings.process"] = payload["process"]
                if "task_settings" in payload:
                    data["settings.task"] = payload["task_settings"]
                if "stage" in payload:
                    data["settings.stage"] = payload["stage"]
                host_acq = (
                    payload.get("host_session")
                    or payload.get("host_acquisition")
                    or payload.get("parent_acquisition")
                )
                if host_acq is not None:
                    data["settings.ephys"] = _normalize_host_block(host_acq)
        elif Path(k).name.endswith("pkl") or Path(k).name.endswith("jsonl"):
            if "df" not in data:
                data["df"] = read_trial_df(filepath=v)
        elif Path(k).name.endswith("csv"):
            pass
        else:
            logging.debug("session_yaml reader: unrecognised key %r: %s", k, v)

    manifest_path = session_dir / "session_manifest.yaml"
    if manifest_path.exists():
        manifest = yaml.safe_load(manifest_path.read_text()) or {}
        subprotocols = manifest.get("subprotocols", [])
        if subprotocols:
            sp_dfs = []
            for sp in subprotocols:
                sp_file = session_dir / sp["file"]
                if sp_file.exists():
                    sp_df = read_trial_df(sp_file)
                    if sp_df is not None:
                        sp_df = sp_df.assign(subprotocol=sp["name"])
                        sp_dfs.append(sp_df)
                else:
                    logging.debug(
                        "session_yaml reader: subprotocol file missing %s", sp_file
                    )
            data["df"] = pd.concat(sp_dfs, ignore_index=True) if sp_dfs else None
            data["subprotocols"] = subprotocols

    return data


def _read_separate_json(session_dir: Path, fmt: dict) -> dict:
    """ARTIFACT_FORMAT_SEPARATE_JSON: separate .msw.settings.*.json + df file."""
    files = _msw_files_dict(session_dir)
    data: dict = {}

    for k, v in files.items():
        if Path(k).name.endswith("csv"):
            pass
        elif Path(k).name.endswith("pkl") or Path(k).name.endswith("jsonl"):
            data["df"] = read_trial_df(filepath=v)
        elif k.endswith("json") and ".msw." in v:
            data[k.replace(".json", "")] = read_json(file=v)
        else:
            logging.debug("separate_json reader: unrecognised key %r: %s", k, v)

    for k, v in files.items():
        if k.endswith("settings.json") and "settings.process" not in data:
            data["settings.process"] = read_json(v)
        elif k.endswith("settings") and "settings.task" not in data:
            data["settings.task"] = read_json(v)

    return data


def _read_legacy(session_dir: Path, fmt: dict) -> dict:
    """ARTIFACT_FORMAT_LEGACY: task_settings.py + switching.pkl/csv."""
    all_files = [str(p) for p in session_dir.glob("*")]
    data: dict = {}

    for v in all_files:
        name = Path(v).name
        if name == "task_settings.py" or name.endswith(".task_settings.py"):
            data["settings.task"] = read_settings_py(file=v)
        elif name.endswith(".pkl") or name.endswith("switching.pkl"):
            if "df" not in data:
                data["df"] = read_trial_df(filepath=v)
        elif name.endswith(".csv") or name.endswith("switching.csv"):
            pass

    return data


_READER_DISPATCH = {
    ARTIFACT_FORMAT_SESSION_YAML: _read_session_yaml,
    ARTIFACT_FORMAT_SEPARATE_JSON: _read_separate_json,
    ARTIFACT_FORMAT_LEGACY: _read_legacy,
}


def read_session_data(session_dir=None):
    """Read raw session data from a directory, dispatching on artifact format.

    Args:
        session_dir: Path to the session directory.

    Returns:
        Dict with keys: ``df``, ``settings.task``, ``settings.process``,
        ``settings.stage``, ``settings.ephys``, ``msw_version``,
        ``namespace_version``, ``artifact_format``, ``is_legacy_session``,
        ``is_complete_session``, ``is_ephys_session``.

    Raises:
        ValueError: If no registered reader handles the detected artifact format.
        AssertionError: If ``session_dir`` does not exist.
    """
    session_dir = Path(session_dir)
    assert session_dir.exists()

    fmt = detect_session_format(session_dir)
    artifact_format = fmt["artifact_format"]
    is_legacy = test_is_legacy_format(session_dir=session_dir)

    reader = _READER_DISPATCH.get(artifact_format)
    if reader is None:
        raise ValueError(
            f"No reader registered for artifact format {artifact_format!r}"
        )

    data = reader(session_dir, fmt)

    data["namespace_version"] = fmt["namespace_version"]
    data["artifact_format"] = artifact_format
    data["is_legacy_session"] = is_legacy
    _attach_msw_version(data, is_legacy)
    data["is_complete_session"] = _check_completeness(data, is_legacy)
    data["is_ephys_session"] = "settings.ephys" in data

    return data
