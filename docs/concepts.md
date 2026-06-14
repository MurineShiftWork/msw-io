# Concepts

## Session namespace

Every MSW session has a canonical basename that encodes three fields
separated by double underscores:

```
{subject}__{datetime}__{task}
```

Example: `mouse_01__20260514_143022_123456__gonogo`

Two datetime precisions are defined:

| Version | Precision | Example datetime |
|---|---|---|
| `v1` (current) | microseconds | `20260514_143022_123456` |
| `legacy` | seconds | `20210718_152153` |

`parse_session_basename` auto-detects the version.  `generate_session_paths`
always writes `v1`.

### Directory layout

A typical subject directory looks like:

```
/data/mouse_01/
  session__20260514_143022_123456__session_gonogo/   <- acquisition container
    mouse_01__20260514_143022_123456__gonogo/         <- session directory
      mouse_01__20260514_143022_123456__gonogo.msw.session.yaml
      mouse_01__20260514_143022_123456__gonogo.msw.jsonl
```

The *session directory* (innermost) is what `load_session` accepts.
The *acquisition container* is what `load_acquisition` accepts.

## Artifact formats

msw-io supports three on-disk formats, detected automatically:

| Format | Indicator | Era |
|---|---|---|
| `session_yaml` | `.msw.session.yaml` present | current (MSW >= 1.0) |
| `separate_json` | `.msw.settings.*.json` files | intermediate |
| `legacy` | `task_settings.py` present | pre-namespace |

All three formats are read into the same `MswSession` model.

## Trial data codec

Trial data is stored as newline-delimited JSON (JSONL) with the extension
`.msw.jsonl`.  The first line is a version header:

```json
{"_msw_version": "1.0.0"}
```

Each subsequent line is one trial dict.  Encoding rules:

- **Numpy arrays** - converted to plain lists
- **Python tuples** - encoded as `{"__tuple__": [...]}` so they survive
  the JSON round-trip (JSON arrays would lose the distinction)
- **Floats** - rounded to 4 decimal places to avoid floating-point drift

`load_trial_data` reverses the tuple encoding automatically.

Legacy `.pkl` sessions are also readable; they are loaded via
`pandas.read_pickle` and require `pyarrow` to be installed.

## MswSession model

`load_session` returns an `MswSession` Pydantic model.  Key fields:

| Field | Description |
|---|---|
| `df` | Trial DataFrame (one row per trial) |
| `settings_task` | Task parameter dict |
| `settings_process` | Process/acquisition metadata |
| `settings_ephys` | Ephys host-session linking block |
| `is_complete` | All required artifacts present and loadable |
| `is_ephys` | Ephys block present in the session |

## Namespace package

msw-io is a *namespace contributor*: its Python package lives at
`murineshiftwork.readers`, `murineshiftwork.io`, and
`murineshiftwork.namespace` - the same top-level namespace used by the
`murineshiftwork` acquisition stack.  Both packages can coexist in the
same environment; neither requires the other.
