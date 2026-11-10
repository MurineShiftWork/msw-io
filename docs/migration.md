# Namespace migration

`msw-io-migrate` renames data written under older namespace shapes to the current
one, in place. With msw-core installed the same command is `msw data migrate`.

| On disk | Becomes |
|---|---|
| `{sub}__{dt}__{task}` | `{sub}__{dt}__msw__{task}` |
| `{sub}__{dt}__{task}__vN`, `{sub}__{dt}__msw__{task}__vN` | `{sub}__{dt}__msw__{task}` |
| `{sub}__{dt}__video_flir__vN` (any typed acq) | `{sub}__{dt}__video_flir` |
| `{sub}__{dt}__msw__test_x` | `{sub}__{dt}__msw___test_x` |
| container `{sub}__{dt}__session_{task}` | `{sub}__{dt}` (`--level container` or `all`) |
| `..__optotagging/..__optotagging__{sub}/` | peer `{sub}__{rec_dt}__video_rce` (`--flatten-optotagging`) |

For each acquisition it renames the directory and every file starting with the old
basename (subdirectories included), rewrites the old basename inside YAML and JSON
files, and updates or creates `acquisition_manifest.yaml` (the dropped `__vN` goes
to `metadata.task_version`) and the container's `session_manifest.yaml`. A
directory already in the current shape is left alone, so a second `--apply` does
nothing.

## Running it on a rig

Run against the directory that holds the subject folders:

```bash
msw-io-migrate /data --audit
msw-io-migrate /data --level all --report migrate_dry_run.json
# review migrate_dry_run.json: actions, conflicts, skipped
msw-io-migrate /data --level all --apply --report migrate_applied.json
msw-io-migrate /data --audit
```

1. `--audit` is read-only. It counts the acq_type, task, session_type and version
   tokens and exits 1 when an acq_type is outside the enum or a test/calibration
   task lacks its leading `_`.
2. Without `--apply` nothing is written. Every planned rename is printed, and
   `--report` writes them as JSON (`actions`, `conflicts`, `skipped`, `summary`)
   so the dry run can be kept centrally.
3. `--apply` executes the same plan.
4. The closing `--audit` should exit 0. The audit also scans `_`-prefixed test
   subjects, which migration skips unless `--include-test` is given.

Narrow a run with `--subjects`, `--shape legacy3comp|vN|typed`, `--acq-type` and
`--level acquisition|container|all` (default `acquisition`). `--no-create-manifests`
only updates manifests that already exist.

## Collisions

A target name that already exists is a collision. It is classified DUPLICATE when
both trees hold the same relative file names with the same sizes, CONFLICT
otherwise; contents are not compared, so large files are not read.

| `--on-conflict` | DUPLICATE | CONFLICT |
|---|---|---|
| `skip` (default) | left in place, exit 1 | left in place, exit 1 |
| `quarantine` | moved to the quarantine dir | moved to the quarantine dir |
| `delete` | removed | moved to the quarantine dir |

The quarantine dir defaults to `<data_root>/_migration_quarantine/<parent>/` and is
never scanned as a subject; `--quarantine-dir` moves it. `delete` on a DUPLICATE
is the only path that removes data.

## Refusals and exit status

`--apply` is refused (exit 2) when the path is not a directory or holds no subject
dirs, i.e. no child `S` containing a `S__<datetime>...` container. This catches a
subject or session folder passed by mistake. Otherwise the exit status is 1 when
collisions were left in place, else 0.

Directories that parse as an acquisition needing migration but hold no direct
files (the optotagging subdirectory layout without `--flatten-optotagging`) are
listed under `skipped` and left untouched.
