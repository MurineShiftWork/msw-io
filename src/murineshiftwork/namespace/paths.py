"""MSW session namespace: path generation and basename parsing.

The MSW namespace (v4) hierarchy is subject > session > acquisition > file.

Session container: ``{subject}__{datetime}[__{session_type}]``
Acquisition:       ``{subject}__{datetime}__{acq_type}[__v{n}]``
File:              ``{acq_basename}.msw.{artifact}``

Two datetime precisions are supported for legacy compatibility:

- ``v1`` (current): microsecond precision -- ``20260514_143022_123456``
- ``legacy``: second precision -- ``20210718_152153``
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Namespace versions (datetime precision formats)

NAMESPACE_V1 = "v1"
NAMESPACE_LEGACY = "legacy"

CURRENT_NAMESPACE_VERSION = NAMESPACE_V1

_NAMESPACE_FORMATS: dict[str, str] = {
    NAMESPACE_V1: "%Y%m%d_%H%M%S_%f",
    NAMESPACE_LEGACY: "%Y%m%d_%H%M%S",
}

_PARSE_ORDER = [NAMESPACE_V1, NAMESPACE_LEGACY]

MSW_DATETIME_FORMAT = _NAMESPACE_FORMATS[CURRENT_NAMESPACE_VERSION]

# Acquisition type vocabulary.
_KNOWN_ACQ_TYPES: frozenset[str] = frozenset(
    {"msw", "pxi", "photo", "video_rce", "video_flir"}
)

# Matches version suffix components: v1, v2, v12, etc.
_VERSION_RE = re.compile(r"^v(\d+)$")

# ---------------------------------------------------------------------------
# NamespaceBuilder (lazy)

_MSW_BUILDER = None


def get_msw_builder():
    """Return the module-level MSW NamespaceBuilder (lazy-loaded)."""
    global _MSW_BUILDER
    if _MSW_BUILDER is None:
        from acquisition_namespace import NamespaceBuilder

        _MSW_BUILDER = NamespaceBuilder.from_yaml(
            Path(__file__).parent / "namespace.msw.yaml"
        )
    return _MSW_BUILDER


# ---------------------------------------------------------------------------
# Validation

_FORBIDDEN_PATH_CHARS = re.compile(r'[#@!$%^&*()+=\[\]{};:\'",<>?\\|`~ ]')


def _validate_path_component(value: str, field: str) -> None:
    if _FORBIDDEN_PATH_CHARS.search(value):
        bad = _FORBIDDEN_PATH_CHARS.findall(value)
        raise ValueError(
            f"{field} contains forbidden characters {bad!r}: {value!r}. "
            "Use only letters, digits, hyphens, and underscores."
        )
    if "__" in value:
        raise ValueError(
            f"{field} contains double-underscore (__), which is the namespace "
            f"separator: {value!r}"
        )


# ---------------------------------------------------------------------------
# Structured subject helpers (v4.1)
#
# Field patterns live in namespace.msw.yaml under levels.subject_id,
# levels.animal_id, and levels.extra_field.  Validation delegates to
# NamespaceBuilder (via get_msw_builder()) so there are no duplicated patterns.


def parse_subject(subject: str) -> dict:
    """Parse a structured v4.1 subject string into its component fields.

    Returns dict with keys:
        subject_id (str), animal_id (str), tag_id (str|None), fields (list[str]).

    ``tag_id`` is a convenience alias for ``fields[0]`` (None if no extra fields).
    ``fields`` contains all extra tokens after subject_id and animal_id, in order.
    Older subjects with 4-5 parts parse without error; extra parts go to ``fields``.

    Raises ValueError if the string does not match the required prefix format.
    """
    parts = subject.split("_")
    if len(parts) < 2:
        raise ValueError(
            f"Subject {subject!r} must contain at least subject_id and animal_id "
            "separated by '_' (e.g. 't004_m2045')."
        )
    builder = get_msw_builder()
    try:
        sid = builder.validate_field("subject_id", parts[0])
    except ValueError as exc:
        raise ValueError(
            f"subject_id {parts[0]!r}: expected letter(s) followed by digits "
            "(e.g. t004, seq001)."
        ) from exc
    try:
        aid = builder.validate_field("animal_id", parts[1])
    except ValueError as exc:
        raise ValueError(
            f"animal_id {parts[1]!r}: expected single letter followed by digits "
            "(e.g. m2045, r001)."
        ) from exc
    fields: list[str] = []
    for token in parts[2:]:
        try:
            builder.validate_field("extra_field", token)
        except ValueError as exc:
            raise ValueError(
                f"Extra field {token!r}: expected alphanumeric token (e.g. 4A7B, batch2)."
            ) from exc
        fields.append(token)
    return {
        "subject_id": sid,
        "animal_id": aid,
        "tag_id": fields[0] if fields else None,
        "fields": fields,
    }


def make_subject(subject_id: str, animal_id: str, *extra_fields: str) -> str:
    """Construct and validate a v4.1 subject string.

    Args:
        subject_id: Lab/experiment label, e.g. ``"t004"``, ``"seq001"``.
            Pattern: one or more letters followed by digits.
        animal_id: Central registry ID, e.g. ``"m2045"``, ``"r001"``.
            Pattern: single letter followed by digits.
        *extra_fields: Zero or more extra tokens appended in order.
            By convention the first is the physical tag (RFID, eartag, implant
            serial), e.g. ``"4A7B"``, ``"LR3"``.

    Returns:
        Validated subject string, e.g. ``"t004_m2045"`` or
        ``"t004_m2045_4A7B_batch2"``.
    """
    subject = "_".join([subject_id, animal_id, *extra_fields])
    parse_subject(subject)
    return subject


# ---------------------------------------------------------------------------
# Parsing


def _parse_datetime(dt_str: str) -> tuple[datetime, str]:
    """Return (datetime, namespace_version) for a datetime string, or raise."""
    for version in _PARSE_ORDER:
        try:
            return datetime.strptime(dt_str, _NAMESPACE_FORMATS[version]), version
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime {dt_str!r}. Tried: {_PARSE_ORDER}")


def parse_acquisition_basename(basename: str) -> dict:
    """Parse an acquisition directory basename into its components.

    Handles both v4 basenames (3 or 4 components) and legacy 3-component
    basenames where the third component is a task name rather than a typed
    acquisition identifier.

    Returns dict with keys:
        subject, datetime, datetime_str, acq_type, acq_version,
        task, namespace_version, is_legacy_acquisition.
    """
    parts = str(basename).split("__")
    if len(parts) < 2:
        raise ValueError(f"Cannot parse acquisition basename: {basename!r}")

    # Find datetime by scanning parts
    dt = dt_str = ns_version = None
    dt_idx = None
    for i, part in enumerate(parts):
        try:
            dt, ns_version = _parse_datetime(part)
            dt_str = part
            dt_idx = i
            break
        except ValueError:
            continue

    if dt_idx is None:
        raise ValueError(
            f"No datetime component found in acquisition basename: {basename!r}"
        )

    subject = "__".join(parts[:dt_idx])
    tail = parts[dt_idx + 1 :]

    if not tail:
        raise ValueError(
            f"Acquisition basename has no type component after datetime: {basename!r}"
        )

    acq_version: int | None = None
    task: str | None = None
    is_legacy = False

    # v4.3 grammar: subject__datetime__acq_type[__task][__vN]. The acq_type is a
    # known enum token; an optional task token follows (visible in the path), and
    # a trailing __vN is the (legacy) acquisition version. When the first token is
    # NOT a known acq_type it is a legacy basename whose third component is the
    # task name and whose acq system is implicitly "msw".
    if tail[0] in _KNOWN_ACQ_TYPES:
        acq_type = tail[0]
        rest = tail[1:]
    else:
        acq_type = "msw"
        is_legacy = True
        rest = tail

    for tok in rest:
        version_match = _VERSION_RE.match(tok)
        if version_match:
            acq_version = int(version_match.group(1))
        elif task is None:
            task = tok
        else:  # defensive: extra non-version tokens fold into the task
            task = f"{task}__{tok}"

    return {
        "subject": subject,
        "datetime": dt,
        "datetime_str": dt_str,
        "acq_type": acq_type,
        "acq_version": acq_version,
        "task": task,
        "namespace_version": ns_version,
        "is_legacy_acquisition": is_legacy,
    }


def parse_session_basename(basename: str) -> dict:
    """Parse a session/acquisition basename into subject, datetime, task.

    Compatibility shim over parse_acquisition_basename(). Returns the same
    keys as the original function: subject, datetime, datetime_str, task,
    namespace_version.
    """
    info = parse_acquisition_basename(basename)
    return {
        "subject": info["subject"],
        "datetime": info["datetime"],
        "datetime_str": info["datetime_str"],
        "task": info["task"] or info["acq_type"],
        "namespace_version": info["namespace_version"],
    }


# ---------------------------------------------------------------------------
# Session path generation


def generate_session_paths(
    subject: str,
    task: str,
    basepath: str | Path,
    acq_type: str = "msw",
    acq_version: int | None = 1,
    session_type: str | None = None,
    version: str = CURRENT_NAMESPACE_VERSION,
    default_subject: str = "_test_subject",
    linked_to: str | None = None,
    datetime_str: str | None = None,
    printout: bool = True,
) -> dict:
    """Generate a validated session path dictionary (v4 namespace).

    Builds the session container (``subject__datetime[__session_type]``) and
    acquisition basename (``subject__datetime__acq_type[__vN]``), then derives
    all associated paths under ``basepath``.

    Tasks whose name starts with ``_test__`` are redirected to
    ``default_subject`` so test runs do not pollute real subject directories.

    Args:
        subject: Animal/subject identifier. Must not contain ``__``.
        task: Task name. Used for the ``task`` key in returned dict only; not
            part of the v4 path structure.
        basepath: Root data directory.
        acq_type: Acquisition type identifier (``"msw"``, ``"pxi"``,
            ``"photo"``, ``"video_rce"``, ``"video_flir"``). Default ``"msw"``.
        acq_version: Integer format version appended as ``__vN`` on the
            acquisition basename. Defaults to ``1`` so MSW writes always carry a
            version. Pass ``None`` to omit the version component for external,
            unversioned acquisition types (e.g. ``pxi``). Version is at the
            acquisition level, not the session container.
        session_type: Optional task-type label appended to the session
            container: ``subject__datetime__session_type``.
        version: Datetime precision format -- ``"v1"`` (default) or
            ``"legacy"``.
        default_subject: Subject name used when task starts with ``_test__``.
        linked_to: Override the entire session container name verbatim.
        datetime_str: Re-use an existing datetime string instead of generating
            a new one.  Pass ``session_paths["datetime"]`` from the primary
            acquisition when creating a sibling (e.g. ``video_flir``) so both
            basenames share the same timestamp.
        printout: Print generated paths to stdout.

    Returns:
        Dict with keys: ``subject``, ``datetime``, ``task``, ``acq_type``,
        ``acq_version``, ``basepath``, ``namespace_version`` (datetime
        precision), ``namespace_spec_version`` (spec semver, e.g. ``"4.2"``),
        ``host_session_name``, ``acquisition_name``, ``session_basename``,
        ``session_folder``, ``session_folder_relative``, ``session_file_path``.
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

    dt = (
        datetime_str
        if datetime_str is not None
        else datetime.now().strftime(_NAMESPACE_FORMATS[version])
    )

    builder = get_msw_builder()

    # --- Session container (session level) ---
    if linked_to:
        session_container = linked_to
    else:
        _sess_values = {"subject": subject, "datetime": dt}
        if session_type:
            _sess_values["session_type"] = session_type
        session_container = builder.build_path("session", _sess_values)

    # --- Acquisition basename (acquisition level) ---
    # v4.3: the task token is part of the path ONLY for the behaviour acq system
    # (acq_type == "msw"). Typed acquisitions -- video_rce, video_flir, pxi,
    # photo -- never carry it, so downstream camera/ephys consumers are not handed
    # the behaviour task tag (e.g. a video_flir sibling stays "...__video_flir",
    # not "...__video_flir__sequence").
    _acq_values = {"subject": subject, "datetime": dt, "acq_type": acq_type}
    if acq_type == "msw" and task and not str(task).startswith("_test"):
        _validate_path_component(str(task), "Task name")
        _acq_values["task"] = str(task)
    if acq_version is not None:
        _acq_values["version"] = str(acq_version)
    session_basename = builder.build_path("acquisition", _acq_values)

    session_folder = basepath / subject / session_container / session_basename

    session_paths = {
        "subject": subject,
        "datetime": dt,
        "task": task,
        "acq_type": acq_type,
        "acq_version": acq_version,
        "basepath": basepath,
        "namespace_version": version,
        "namespace_spec_version": builder.spec.version,
        "host_session_name": session_container,
        "acquisition_name": session_basename,
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
    """Compatibility shim - calls generate_session_paths with current defaults."""
    return generate_session_paths(
        subject=subject,
        task=task,
        basepath=basepath,
        version=CURRENT_NAMESPACE_VERSION,
        default_subject=default_subject,
        linked_to=linked_to,
        printout=printout,
    )
