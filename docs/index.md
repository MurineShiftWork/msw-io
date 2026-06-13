# msw-io

[![PyPI](https://img.shields.io/pypi/v/msw-io.svg)](https://pypi.org/project/msw-io)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Murine Shift Work session data IO: file codec, namespace utilities, and session readers.

Provides a lean, installable library for reading and writing MSW session data without
requiring the full `murineshiftwork` acquisition stack.

## Key features

- **Session readers**: load MSW session data (JSONL, PKL, YAML) into structured models
- **Namespace utilities**: build and parse MSW session paths from the canonical namespace spec
- **IO codec**: save and load trial data with numpy/tuple encoding
- **Standalone**: install without `murineshiftwork` for analysis-only environments

## Quick start

```python
from msw_io.readers import load_session

session = load_session("/data/mouse_01/session_dir/acquisition_dir")
print(session.task, session.n_trials)
```

```python
from msw_io.namespace import generate_session_paths

paths = generate_session_paths("mouse_01", "sequence", "/data", printout=False)
print(paths["session_basename"])
```
