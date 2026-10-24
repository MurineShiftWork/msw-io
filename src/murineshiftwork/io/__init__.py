"""JSONL trial data codec for MSW sessions (MSW_FILE_VERSION 1.0.0).

Format: newline-delimited JSON. First line is a version header.
Numpy arrays are serialised as plain lists; on load they remain lists,
which is compatible with all downstream DataFrame operations.

Tuple preservation
------------------
JSON has no tuple type: both lists and tuples serialise as arrays. To preserve
Python tuples across the round-trip, tuples are encoded as {"__tuple__": [...]}
and decoded back to tuples on load. This keeps the computational interface
identical between JSONL and legacy pkl sessions (e.g. block_type_values).
"""

import contextlib
import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path

import numpy as np

MSW_FILE_VERSION = "1.0.0"


def _encode_tuples(obj):
    """Recursively replace tuples with {"__tuple__": [...]} before JSON encoding."""
    if isinstance(obj, tuple):
        return {"__tuple__": [_encode_tuples(v) for v in obj]}
    if isinstance(obj, dict):
        return {k: _encode_tuples(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_encode_tuples(v) for v in obj]
    return obj


def _decode_tuples(obj):
    """Recursively restore {"__tuple__": [...]} sentinels to Python tuples."""
    if isinstance(obj, dict):
        if "__tuple__" in obj and len(obj) == 1:
            return tuple(_decode_tuples(v) for v in obj["__tuple__"])
        return {k: _decode_tuples(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decode_tuples(v) for v in obj]
    return obj


_FLOAT_DECIMALS = 4


def _round_floats(obj):
    """Recursively round all floats to _FLOAT_DECIMALS decimal places."""
    if isinstance(obj, float):
        return round(obj, _FLOAT_DECIMALS)
    if isinstance(obj, dict):
        return {k: _round_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_round_floats(v) for v in obj)
    if isinstance(obj, np.ndarray):
        if np.issubdtype(obj.dtype, np.floating):
            return obj.round(_FLOAT_DECIMALS).tolist()
        return obj.tolist()
    if isinstance(obj, np.floating):
        return round(float(obj), _FLOAT_DECIMALS)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


class _NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.ndarray):
            if np.issubdtype(obj.dtype, np.floating):
                return obj.round(_FLOAT_DECIMALS).tolist()
            return obj.tolist()
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return round(float(obj), _FLOAT_DECIMALS)
        if isinstance(obj, np.bool_):
            return bool(obj)
        return super().default(obj)


# On Windows a reader holding the target open makes os.replace fail with PermissionError; retry
# briefly before falling back to an in-place copy (never drop the write).
_REPLACE_ATTEMPTS = 5
_REPLACE_RETRY_DELAY_S = 0.05


def _atomic_write_text(filepath: Path, text: str) -> None:
    """Replace ``filepath`` with ``text`` atomically (temp sibling, fsync, ``os.replace``).

    A crash mid-write leaves the previous file intact. The temp file is created with
    ``open(..., "x")`` so it gets the normal umask permissions, and an existing target's mode is
    copied across. If the swap keeps failing with ``PermissionError`` (Windows, target held open
    by a reader) the content is copied over the target in place instead, with a warning.
    """
    tmp = filepath.with_name(f".{filepath.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with tmp.open("x") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if filepath.exists():
            with contextlib.suppress(OSError):
                shutil.copymode(filepath, tmp)
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                tmp.replace(filepath)  # os.replace: atomic swap
                return
            except PermissionError:
                if attempt + 1 < _REPLACE_ATTEMPTS:
                    time.sleep(_REPLACE_RETRY_DELAY_S)
        logging.warning(
            f"Could not atomically replace {filepath} (held open?); rewriting in place"
        )
        shutil.copyfile(tmp, filepath)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def save_trial_data(trial_data_list: list, filepath: str | Path) -> None:
    """Save a list of trial dicts to a JSONL file.

    Replaces any existing file atomically: every trial is encoded first, then the file is
    written to a temporary sibling and swapped in with ``os.replace``, so a crash or an
    unencodable trial never leaves a truncated file behind (the previous contents survive).
    The first line is a version header; subsequent lines are one JSON object per trial.
    Numpy arrays are converted to lists; tuples are encoded as ``{"__tuple__": [...]}``
    so they survive the round-trip through ``load_trial_data``.

    Args:
        trial_data_list: List of per-trial dicts as returned by the task.
        filepath: Destination path (parent directories are created if absent).
    """
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"_msw_version": MSW_FILE_VERSION})]
    lines.extend(
        json.dumps(_round_floats(_encode_tuples(trial)), cls=_NumpyEncoder)
        for trial in trial_data_list
    )
    _atomic_write_text(filepath, "".join(line + "\n" for line in lines))
    logging.debug(f"Saved {len(trial_data_list)} trials to {filepath}")


def load_trial_data(filepath) -> list:
    """Load trial dicts from a JSONL file written by ``save_trial_data``.

    Skips the version header line and restores ``{"__tuple__": [...]}``
    sentinels back to Python tuples.

    Args:
        filepath: Path to the ``.jsonl`` file.

    Returns:
        List of per-trial dicts with tuples restored.
    """
    filepath = Path(filepath)
    trials = []
    with filepath.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if "_msw_version" in obj:
                continue
            trials.append(_decode_tuples(obj))
    return trials


# The swappable trial-data writer lives beside the codec it wraps. Re-exported here so callers use
# `from murineshiftwork.io import TrialDataWriter, JsonlTrialDataWriter`. Imported last to avoid a
# cycle (JsonlTrialDataWriter uses save_trial_data above, via a lazy import).
from murineshiftwork.io.trial_writer import (  # noqa: E402, F401
    JsonlTrialDataWriter,
    TrialDataWriter,
)
