# Local and CI quality guards

Use the existing Rider-Pi environment; device Python is 3.9 and Ruff is pinned
to 0.6.9. See [environment policy](ENVIRONMENT_POLICY.md) and
[Sonar/coverage workflow](QUALITY_GATE.md).

## Stages and scope

[.pre-commit-config.yaml](../.pre-commit-config.yaml) defines:

| Check | Local stage | CI |
| --- | --- | --- |
| Ruff check/fix and format | Commit and normal pre-commit stages | Quality Guard checks the repository |
| Python file length | Pre-push/manual | Quality Guard checks changed Python files against base/head |
| Removed imports | Default hook stages, including commit; always_run | Run the script explicitly for the same dedicated check |

The removed-import hook is not confined to pre-push. Hook installation and its
interpreter are local environment configuration; do not assume pre_commit is
installed in every virtualenv. Direct scripts are available without that wrapper.
Do not bypass hooks for a published change.

## Commands

Run from the repository root:

```sh
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python scripts/dev_check-file-length.py --base origin/main --head HEAD
.venv/bin/python scripts/dev_check-legacy-imports.py
```

The size checker compares committed revisions; use explicit file arguments to
inspect uncommitted edits. Exit 0 includes advisory warnings; exit 1 means a
hard violation or unreadable input/diff.

| Physical Python lines, including comments and blanks | Result |
| --- | --- |
| 0–600 | Pass |
| 601–800 | Advisory warning; inspect cohesion |
| More than 800 | Failure |

All changed Python files, including tests/scripts, follow the same policy.
Untouched historical files do not block an unrelated change. The old
allow-oversize label is not an exemption. Split coherent responsibilities and
preserve public imports; file length is not a CPU or memory measurement.

## Removed-import migration

The authoritative list is
[scripts/dev_check-legacy-imports.py](../scripts/dev_check-legacy-imports.py).
It blocks removed voice, face and launcher paths and removed mixins.
Representative replacements:

| Removed path | Maintained replacement |
| --- | --- |
| apps.voice.capture / playback | apps.voice.audio.capture / playback |
| apps.voice.service_impl | apps.voice.svc_file |
| apps.voice.state / ptt_state | apps.voice.stream.state |
| apps.voice.transport / ws_transport / stream_transport | apps.voice.stream.transport |
| apps.voice.stream.service | apps.voice.stream.svc_streaming |
| apps.voice.main | apps.voice.cli |
| apps.ui.face.driver_ili9xx | drivers.lcd.driver_ili9xx |

A reported false positive requires source inspection and a justified change,
not a disabled global check. Run relevant isolated tests after import changes.
