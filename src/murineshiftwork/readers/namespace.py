import logging
from pathlib import Path

from murineshiftwork.namespace.msw_files import is_msw_file

# ---------------------------------------------------------------------------
# Artifact format constants

ARTIFACT_FORMAT_LEGACY = "legacy"
ARTIFACT_FORMAT_SEPARATE_JSON = "separate_json"
ARTIFACT_FORMAT_SESSION_YAML = "session_yaml"


# ---------------------------------------------------------------------------
# Legacy detection helpers


def test_is_legacy_msw_file(file):
    """Test if file is legacy namespace file."""
    file = str(file)
    return (
        Path(file).name.endswith("switching.pkl")
        or Path(file).name.endswith("switching.csv")
        or Path(file).name.endswith("task_settings.py")
    )


def test_is_recognized_msw_file(file):
    """Test if file is current or legacy namespace file."""
    file = str(file)
    # Back-compat: sequence task previously wrote *.df.jsonl without .msw. segment
    if file.endswith(".df.jsonl") and not is_msw_file(file):
        return True
    return is_msw_file(file) or test_is_legacy_msw_file(file=file)


def test_is_legacy_format(session_dir=None):
    """Test if files in session folder are legacy namespace file."""
    session_dir = Path(session_dir)
    assert session_dir.exists()

    session_files = [str(p) for p in session_dir.glob("*")]

    for f in session_files:
        if test_is_legacy_msw_file(file=f):
            logging.debug(
                f"Is legacy MSW data format (identified on file: '{Path(f).name}'): {str(session_dir)}"
            )
            return True

    return False


# ---------------------------------------------------------------------------
# Format detection


def _infer_session_basename(session_dir: Path) -> str | None:
    """Extract session basename from .msw. filenames in directory.

    Prefers .msw.session.yaml (canonical) over other .msw. files so that
    multi-protocol sessions resolve to the correct session-level basename.
    """
    candidates = [f for f in session_dir.iterdir() if ".msw." in f.name]
    if not candidates:
        return None
    for f in candidates:
        if f.name.endswith(".msw.session.yaml"):
            return f.name.split(".msw.")[0]
    return min(candidates, key=lambda f: len(f.name.split(".msw.")[0])).name.split(
        ".msw."
    )[0]


def detect_artifact_format(session_dir: Path) -> str:
    """Detect artifact storage format from files present in session_dir."""
    session_dir = Path(session_dir)
    names = {p.name for p in session_dir.iterdir()}

    if any(
        n.endswith("task_settings.py")
        or n.endswith("switching.pkl")
        or n.endswith("switching.csv")
        for n in names
    ):
        return ARTIFACT_FORMAT_LEGACY

    if any(".msw.session.yaml" in n for n in names):
        return ARTIFACT_FORMAT_SESSION_YAML

    if any(".msw.settings.process.json" in n for n in names):
        return ARTIFACT_FORMAT_SEPARATE_JSON

    return ARTIFACT_FORMAT_LEGACY


def _read_namespace_version_from_metadata(session_dir: Path) -> str | None:
    """Return the authoritative spec version written into the session, or None.

    Checks the self-describing sinks written at acquisition time (v4.2+):
    the ``.msw.session.yaml`` ``process.namespace_version`` field first, then
    the ``msw_namespace_version`` key of either manifest. Returns None when the
    session predates metadata stamping (its version must be inferred).
    """
    import yaml

    for f in session_dir.glob("*.msw.session.yaml"):
        try:
            payload = yaml.safe_load(f.read_text()) or {}
        except Exception:
            continue
        ver = (payload.get("process") or {}).get("namespace_version")
        if ver:
            return str(ver)
    for manifest_name in ("acquisition_manifest.yaml", "session_manifest.yaml"):
        p = session_dir / manifest_name
        if p.exists():
            try:
                data = yaml.safe_load(p.read_text()) or {}
            except Exception:
                continue
            ver = data.get("msw_namespace_version")
            if ver:
                return str(ver)
    return None


def identify_namespace_version(session_dir: Path) -> dict:
    """Decision tree identifying a session's namespace generation.

    Resolution order, most authoritative first:

    1. ``namespace_version`` stamped in session.yaml / a manifest -> use verbatim
       (``source="metadata"``). This is the only path for v4.2+ sessions.
    2. Structural inference from the acquisition basename (``source="inferred"``):

       - acquisition carries a ``__v{n}`` suffix            -> ``"4.2"``
       - typed ``acq_type`` (msw/pxi/photo/video_*), no ver -> ``"4.1"``
       - 3-component, task-named, microsecond datetime      -> ``"4.1"``
       - second-precision datetime                          -> ``"legacy"``
       - basename does not parse                             -> ``"unknown"``

    Returns ``{spec_version, source, acq_type, acq_version, is_legacy}``.
    """
    from murineshiftwork.namespace.paths import parse_acquisition_basename

    session_dir = Path(session_dir)
    stamped = _read_namespace_version_from_metadata(session_dir)
    basename = _infer_session_basename(session_dir) or session_dir.name

    acq_type = acq_version = None
    is_legacy = False
    inferred = "unknown"
    try:
        info = parse_acquisition_basename(basename)
        acq_type = info["acq_type"]
        acq_version = info["acq_version"]
        if info["acq_version"] is not None:
            inferred = "4.2"
        elif info["namespace_version"] == "legacy":  # second-precision datetime
            inferred = "legacy"
            is_legacy = True
        else:
            inferred = "4.1"
            is_legacy = info["is_legacy_acquisition"]
    except ValueError:
        inferred = "unknown"

    if stamped:
        return {
            "spec_version": stamped,
            "source": "metadata",
            "acq_type": acq_type,
            "acq_version": acq_version,
            "is_legacy": False,
        }
    return {
        "spec_version": inferred,
        "source": "inferred",
        "acq_type": acq_type,
        "acq_version": acq_version,
        "is_legacy": is_legacy,
    }


def detect_session_format(session_dir: Path) -> dict:
    """Detect namespace version and artifact format for a session directory."""
    from murineshiftwork.namespace.paths import parse_session_basename

    session_dir = Path(session_dir)
    artifact_format = detect_artifact_format(session_dir)

    basename = _infer_session_basename(session_dir) or session_dir.name

    try:
        info = parse_session_basename(basename)
        namespace_version = info["namespace_version"]
        parse_error = None
    except ValueError as exc:
        namespace_version = None
        parse_error = str(exc)

    ident = identify_namespace_version(session_dir)

    return {
        "basename": basename,
        "namespace_version": namespace_version,
        "namespace_spec_version": ident["spec_version"],
        "namespace_spec_source": ident["source"],
        "artifact_format": artifact_format,
        "parse_error": parse_error,
    }


def validate_session_namespace(session_dir: Path) -> dict:
    """Validate that the session basename conforms to the MSW namespace spec."""
    from murineshiftwork.namespace.paths import parse_session_basename

    session_dir = Path(session_dir)
    basename = _infer_session_basename(session_dir) or session_dir.name

    try:
        info = parse_session_basename(basename)
        return {
            "valid": True,
            "namespace_version": info["namespace_version"],
            "basename": basename,
            "error": None,
        }
    except ValueError as exc:
        return {
            "valid": False,
            "namespace_version": None,
            "basename": basename,
            "error": str(exc),
        }
