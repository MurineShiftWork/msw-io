"""MSW session namespace: path generation and basename parsing.

The MSW namespace encodes subject identity, datetime, and task into a
canonical basename: ``{subject}__{datetime}__{task}``.  Two datetime
precisions are supported:

- ``v1`` (current): microsecond precision — ``20260514_143022_123456``
- ``legacy``: second precision — ``20210718_152153``
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Namespace versions

NAMESPACE_V1 = "v1"  # current: microsecond precision  e.g. 20260514_143022_123456
NAMESPACE_LEGACY = "legacy"  # pre-v1:  second precision    e.g. 20210718_152153

CURRENT_NAMESPACE_VERSION = NAMESPACE_V1

_NAMESPACE_FORMATS: dict[str, str] = {
    NAMESPACE_V1: "%Y%m%d_%H%M%S_%f",
    NAMESPACE_LEGACY: "%Y%m%d_%H%M%S",
}

# Parse order: most-specific first so the longer microsecond format is tried before
# the seconds format (which is a valid prefix of the microsecond string).
_PARSE_ORDER = [NAMESPACE_V1, NAMESPACE_LEGACY]

# Convenience alias kept for callers that import MSW_DATETIME_FORMAT directly.
MSW_DATETIME_FORMAT = _NAMESPACE_FORMATS[CURRENT_NAMESPACE_VERSION]

# ---------------------------------------------------------------------------
# MSW artifact builder

_MSW_BUILDER = None


def get_msw_builder():
    """Return the module-level MSW NamespaceBuilder (lazy-loaded from namespace.msw.yaml)."""
    global _MSW_BUILDER
    if _MSW_BUILDER is None:
        from acquisition_namespace import NamespaceBuilder

        _MSW_BUILDER = NamespaceBuilder.from_yaml(
            Path(__file__).parent / "namespace.msw.yaml"
        )
    return _MSW_BUILDER


# ---------------------------------------------------------------------------
# Parsing


def parse_session_basename(basename: str) -> dict:
    """Parse subject, datetime, task from a session basename.

    Returns dict with keys:
        subject (str), datetime (datetime), datetime_str (str),
        task (str), namespace_version (str).

    Raises ValueError if the basename cannot be parsed.
    """
    builder = get_msw_builder()
    try:
        values = builder.extract_level_values("session", str(basename))
    except ValueError:
        raise ValueError(
            f"Expected 3 '__'-separated parts (subject, datetime, task), "
            f"cannot parse: {basename!r}"
        ) from None

    dt_str = values["datetime"]
    for version in _PARSE_ORDER:
        try:
            dt = datetime.strptime(dt_str, _NAMESPACE_FORMATS[version])
            return {
                "subject": values["subject"],
                "datetime": dt,
                "datetime_str": dt_str,
                "task": values["task"],
                "namespace_version": version,
            }
        except ValueError:
            continue

    raise ValueError(
        f"Cannot parse datetime {dt_str!r} in basename {basename!r}. "
        f"Tried namespace versions: {_PARSE_ORDER}"
    )


# Characters forbidden in subject / task path components.
_FORBIDDEN_PATH_CHARS = re.compile(r'[#@!$%^&*()+=\[\]{};:\'",<>?\\|`~ ]')


def _validate_path_component(value: str, field: str) -> None:
    if _FORBIDDEN_PATH_CHARS.search(value):
        bad = _FORBIDDEN_PATH_CHARS.findall(value)
        raise ValueError(
            f"{field} contains forbidden characters {bad!r}: {value!r}. "
            "Use only letters, digits, hyphens, and underscores."
        )


# ---------------------------------------------------------------------------
# Session path generation


def generate_session_paths(
    subject: str,
    task: str,
    basepath: str | Path,
    version: str = CURRENT_NAMESPACE_VERSION,
    default_subject: str = "_test_subject",
    linked_to: str | None = None,
    printout: bool = True,
) -> dict:
    """Generate a validated session path dictionary for a given namespace version.

    Builds the canonical session basename (``subject__datetime__task``) and
    derives all associated paths under ``basepath``.  Tasks whose name starts
    with ``_test__`` are redirected to ``default_subject`` so test runs do not
    pollute real subject directories.

    Args:
        subject: Animal/subject identifier (letters, digits, hyphens, underscores).
        task: Task name (same character restrictions as ``subject``).
        basepath: Root data directory under which subject folders live.
        version: Namespace version — ``"v1"`` (default) or ``"legacy"``.
        default_subject: Subject name used when task starts with ``_test__``.
        linked_to: If provided, use this string as the host-session container
            name instead of deriving one from the task name.
        printout: Print the generated paths to stdout when ``True``.

    Returns:
        Dict with keys: ``subject``, ``datetime``, ``task``, ``basepath``,
        ``namespace_version``, ``host_session_name``, ``acquisition_name``,
        ``session_basename``, ``session_folder``, ``session_folder_relative``,
        ``session_file_path``.

    Raises:
        ValueError: If ``version`` is not a known namespace version, or if
            ``subject`` or ``task`` contain forbidden characters.
    """
    if version not in _NAMESPACE_FORMATS:
        raise ValueError(
            f"Unknown namespace version {version!r}. "
            f"Choose from: {list(_NAMESPACE_FORMATS)}"
        )

    basepath = Path(basepath)

    if str(task).startswith("_test__"):
        subject = default_subject
    _validate_path_component(subject, "Subject name")

    dt = datetime.now().strftime(_NAMESPACE_FORMATS[version])
    values = {"subject": subject, "datetime": dt, "task": task}

    builder = get_msw_builder()
    session_basename = builder.build_path("session", values)

    if linked_to:
        session_container = linked_to
    else:
        session_container = builder.build_path(
            "session", {**values, "task": f"session_{task}"}
        )

    host_session_name = session_container
    acquisition_name = session_basename
    session_folder = basepath / subject / session_container / session_basename

    session_paths = {
        "subject": subject,
        "datetime": dt,
        "task": task,
        "basepath": basepath,
        "namespace_version": version,
        "host_session_name": host_session_name,
        "acquisition_name": acquisition_name,
        "session_basename": session_basename,
        "session_folder": session_folder.as_posix(),
        "session_folder_relative": session_folder.relative_to(basepath).as_posix(),
        "session_file_path": (session_folder / session_basename).as_posix(),
    }

    if printout:
        print("\n   Session paths: \n")
        for k, v in session_paths.items():
            print(f"{k:>30}:{'':>2}{v}")
        print("\n")

    return session_paths


def build_data_paths(
    basepath=None,
    subject=None,
    task=None,
    default_subject="_test_subject",
    linked_to=None,
    printout=True,
) -> dict:
    """Compatibility shim - calls generate_session_paths with CURRENT_NAMESPACE_VERSION."""
    return generate_session_paths(
        subject=subject,
        task=task,
        basepath=basepath,
        version=CURRENT_NAMESPACE_VERSION,
        default_subject=default_subject,
        linked_to=linked_to,
        printout=printout,
    )
