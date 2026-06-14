# Getting started

## Installation

```bash
pip install msw-io
```

Requires Python 3.11+.

## Reading a session

Point `load_session` at the innermost session directory (the one containing
`.msw.*` artifact files):

```python
from murineshiftwork.readers import load_session

session = load_session("/data/mouse_01/session__20260514_143022_123456__session_gonogo"
                       "/mouse_01__20260514_143022_123456__gonogo")

print(session.subject)          # "mouse_01"
print(session.task)             # "gonogo"
print(session.is_complete)      # True if df + settings present
print(len(session.df))          # number of trials
```

## Reading all sessions in an acquisition

An acquisition container holds one or more session directories (one per
task or sub-protocol run within a continuous recording):

```python
from murineshiftwork.readers import load_acquisition

sessions = load_acquisition(
    "/data/mouse_01/session__20260514_143022_123456__session_gonogo"
)
for s in sessions:
    print(s.basename, s.is_complete)
```

## Reading all sessions for a subject

```python
from murineshiftwork.readers import load_subject

sessions = load_subject("/data/mouse_01")
print(f"{len(sessions)} sessions loaded")
```

## Validating a session

```python
from murineshiftwork.readers.validate import validate_session

result = validate_session("/data/mouse_01/.../session_dir")
# prints a PASS/FAIL summary
print(result.passed)
print(result.issues)
```

## Generating session paths

Use `generate_session_paths` at the start of each acquisition to get the
canonical directory structure for saving data:

```python
from murineshiftwork.namespace import generate_session_paths

paths = generate_session_paths("mouse_01", "gonogo", "/data", printout=False)

print(paths["session_folder"])    # /data/mouse_01/session__...session_gonogo/mouse_01__...gonogo
print(paths["session_basename"])  # mouse_01__20260514_143022_123456__gonogo
```

The `murineshiftwork` acquisition stack calls this internally; use it
directly in custom scripts that create session directories.

## Saving and loading trial data

```python
from murineshiftwork.io import save_trial_data, load_trial_data

trials = [{"trial": 1, "correct": True, "rt": 0.312}, ...]
save_trial_data(trials, "/data/.../session.msw.jsonl")

loaded = load_trial_data("/data/.../session.msw.jsonl")
```

Numpy arrays are stored as lists; Python tuples are preserved across the
round-trip via a `{"__tuple__": [...]}` encoding.
