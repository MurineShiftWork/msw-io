"""Read the up-to-date current-format fixtures (real --simulate runs, v4.2).

fixture_v42_sequence and fixture_v42_fixedsubjects are full v4.2 session
containers (session_manifest.yaml + an acquisition dir with
acquisition_manifest.yaml, .msw.session.yaml, .msw.df.jsonl), captured by
running the tasks under --simulate. These guard that the current acquisition
output reads back through the standard readers.
"""

from pathlib import Path

import pytest

from murineshiftwork.readers.batch import load_session
from murineshiftwork.readers.namespace import ARTIFACT_FORMAT_SESSION_YAML

_DATA = Path(__file__).parent / "data"
_FIXTURES = {
    "sequence": _DATA / "v42_seq",
    "fixedsubjects": _DATA / "v42_fs",
}


def _acq_dir(fixture_root: Path) -> Path:
    """The innermost acquisition dir (the one holding the .msw.session.yaml)."""
    hits = list(fixture_root.rglob("*.msw.session.yaml"))
    assert hits, f"no session.yaml under {fixture_root}"
    return hits[0].parent


@pytest.mark.parametrize("name", sorted(_FIXTURES))
def test_v42_fixture_reads_as_current_format(name):
    root = _FIXTURES[name]
    if not root.exists():
        pytest.skip(f"fixture absent: {root}")
    s = load_session(_acq_dir(root))

    # native current session: session.yaml is the authoritative marker
    assert s.artifact_format == ARTIFACT_FORMAT_SESSION_YAML
    assert s.namespace_version == "v1"
    # trial data loaded and complete
    assert s.df is not None and len(s.df) >= 1
    assert s.is_complete is True
    assert s.is_ephys is False
    # native session has no ingest metadata
    assert s.metadata is None or "source" not in (s.metadata or {})


@pytest.mark.parametrize("name", sorted(_FIXTURES))
def test_v42_fixture_has_manifests(name):
    root = _FIXTURES[name]
    if not root.exists():
        pytest.skip(f"fixture absent: {root}")
    assert list(root.rglob("session_manifest.yaml")), "container manifest missing"
    assert list(root.rglob("acquisition_manifest.yaml")), "acq manifest missing"
