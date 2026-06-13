import logging
from pathlib import Path

from msw_io.namespace.msw_files import is_msw_file

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


def detect_session_format(session_dir: Path) -> dict:
    """Detect namespace version and artifact format for a session directory."""
    from msw_io.namespace.paths import parse_session_basename

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

    return {
        "basename": basename,
        "namespace_version": namespace_version,
        "artifact_format": artifact_format,
        "parse_error": parse_error,
    }


def validate_session_namespace(session_dir: Path) -> dict:
    """Validate that the session basename conforms to the MSW namespace spec."""
    from msw_io.namespace.paths import parse_session_basename

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
