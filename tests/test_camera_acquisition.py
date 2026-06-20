"""Camera acquisition dispatch: detect backend, delegate to backend reader.

The dispatch wraps the per-backend readers (msw_flir_bonsai / rpi_camera_ensemble)
behind a uniform CameraAcquisition. Backend-load tests importorskip the backend
package, so they run wherever the optional dep is installed and skip otherwise;
detection and the error paths need no backend.
"""

from __future__ import annotations

import pytest

from murineshiftwork.readers import (
    CameraAcquisition,
    detect_camera_backend,
    load_camera_acquisition,
)

_FLIR_BASE = "s1__20260620_120000_000000__video_flir__v1"
_RCE_BASE = "s1__20260620_120000_000000__video_rce"


# --- backend detection (no backend package needed) ---


@pytest.mark.parametrize(
    "name,expected",
    [
        (_FLIR_BASE, "flir"),
        (_RCE_BASE, "rce"),
        ("s1__20260620_120000_000000__sequence__v1", None),
        ("not-a-namespace-dir", None),
    ],
)
def test_detect_camera_backend(tmp_path, name, expected):
    d = tmp_path / name
    d.mkdir()
    assert detect_camera_backend(d) == expected


def test_non_camera_dir_raises_value_error(tmp_path):
    d = tmp_path / "s1__20260620_120000_000000__sequence__v1"
    d.mkdir()
    with pytest.raises(ValueError, match="video_flir/video_rce"):
        load_camera_acquisition(d)


def test_missing_directory_raises(tmp_path):
    with pytest.raises(NotADirectoryError):
        load_camera_acquisition(tmp_path / "nope")


# --- FLIR backend (skips if msw_flir_bonsai not installed) ---


def test_load_flir_acquisition(tmp_path):
    pytest.importorskip("msw_flir_bonsai")
    d = tmp_path / _FLIR_BASE
    d.mkdir()
    (d / f"{_FLIR_BASE}.msw.top.0.avi").write_bytes(b"\x00")
    (d / f"{_FLIR_BASE}.msw.top.0.timestamps.csv").write_text("0,0.0,0\n1,0.0167,0\n")

    acq = load_camera_acquisition(d)
    assert isinstance(acq, CameraAcquisition)
    assert acq.backend == "flir"
    assert acq.directory == d
    assert acq.is_complete is True
    # native object reachable for backend-specific access
    assert "top.0" in acq.session.cameras


def test_load_flir_incomplete(tmp_path):
    pytest.importorskip("msw_flir_bonsai")
    d = tmp_path / _FLIR_BASE
    d.mkdir()
    (d / f"{_FLIR_BASE}.msw.top.0.avi").write_bytes(b"\x00")  # no timestamps csv

    acq = load_camera_acquisition(d)
    assert acq.backend == "flir"
    assert acq.is_complete is False


# --- RCE backend (skips if rpi_camera_ensemble not installed) ---


def test_load_rce_empty_is_incomplete(tmp_path):
    pytest.importorskip("rpi_camera_ensemble")
    d = tmp_path / _RCE_BASE
    d.mkdir()  # no agent files
    acq = load_camera_acquisition(d)
    assert acq.backend == "rce"
    assert acq.is_complete is False
