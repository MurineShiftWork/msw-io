# API Reference

## Session readers

### Batch loading

::: murineshiftwork.readers.batch.load_session
    options:
      show_source: false

::: murineshiftwork.readers.batch.load_acquisition
    options:
      show_source: false

::: murineshiftwork.readers.batch.load_subject
    options:
      show_source: false

### Session model

::: murineshiftwork.readers.models.MswSession
    options:
      members: true
      show_source: false

### Validation

::: murineshiftwork.readers.validate.ValidationResult
    options:
      members: true
      show_source: false

::: murineshiftwork.readers.validate.validate_session
    options:
      show_source: false

### Low-level reader

::: murineshiftwork.readers.session.read_session_data
    options:
      show_source: false

---

## Namespace utilities

::: murineshiftwork.namespace.paths.generate_session_paths
    options:
      show_source: false

::: murineshiftwork.namespace.paths.parse_session_basename
    options:
      show_source: false

---

## IO codec

::: murineshiftwork.io.save_trial_data
    options:
      show_source: false

::: murineshiftwork.io.load_trial_data
    options:
      show_source: false
