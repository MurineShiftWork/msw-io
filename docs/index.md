# msw-io

Murine Shift Work session data IO: file codec, namespace utilities, and session readers.

Provides a lean, installable library for reading and writing MSW session data without
requiring the full `murineshiftwork` acquisition stack.  Install it in analysis
environments where you only need to load sessions, not run them.

## Key features

- **Session readers** - load MSW session data (JSONL, PKL, YAML) into structured `MswSession` models
- **Namespace utilities** - build and parse MSW session paths from the canonical `subject__datetime__task` spec
- **IO codec** - save and load trial data with numpy/tuple encoding
- **Standalone** - no dependency on the `murineshiftwork` acquisition stack

## Installation

```bash
pip install msw-io
```

## Quick start

```python
from murineshiftwork.readers import load_session

session = load_session("/data/mouse_01/session__20260514_143022_123456__gonogo")
print(session.subject, session.task)
print(len(session.df))  # number of trials
```

See [Getting started](getting_started.md) for a full walkthrough.
