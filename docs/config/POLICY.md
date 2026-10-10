# Rider-Pi configuration policy

`config/` is the configuration source. The
[environment policy](../ENVIRONMENT_POLICY.md) defines the device/WSL dependency
split. Rider-Pi is a lightweight robot: keep only execution packages required by
the selected profile on the device.

## Sources and overrides

`apps/voice/config.py` loads the selected TOML; `load(None)` uses the repository's
`config/voice.toml`, then applies explicitly supplied overrides. CLI callers can
select a file and apply their own arguments/process settings. Do not assume that
`load(None)` reads `VOICE_CONFIG`. Use existing files in `config/` and local
overrides in `config/local/`. Do not copy Pi hardware configuration into WSL.

| Area | Location |
| --- | --- |
| Voice | `config/voice*.toml` |
| Face and LCD | `config/face.toml` |
| WM8960 ALSA | `config/alsa/asoundrc.wm8960` and `config/alsa/wm8960-apply.sh` |
| Secrets and local overrides | `config/local/`; Git-ignored files |

The installed display orientation is fixed at `FACE_LCD_ROTATE=270`.
The device screen is mounted sideways; routine changes must preserve this rotation.

## Secrets and Git

Keep credentials out of the repository, command history, PR descriptions and logs.
Use environment variables or a Git-ignored file in `config/local/` with permissions
`600`. Existing SSH credentials in `env.ssh.local` remain local; verify the actual
filename and `.gitignore` rule before editing. Diagnose presence or identity of a
credential without displaying its value.

Use `auth = "env:OPENAI_API_KEY"` or `auth = "file:config/local/openai.key"` in TOML.
Do not restore the retired `bashenv:` scheme. Scripts read configuration, preserve
existing ENV values and do not append secrets to user profiles.

## WSL and the device

Full software tests and development tools belong to the existing local
`Rider-Pi/.venv`. Rider-Pc and Venom retain separate stacks. Do not install globally,
create another venv for each worktree, or install a package for every import error.
First identify the selected profile, interpreter and declared requirements.

Explicitly approved WSL preparation reuses that environment:

```bash
/home/pi/Rider-Pi/.venv/bin/python -m pip install -r config/agent/requirements-wsl.txt
/home/pi/Rider-Pi/.venv/bin/python -m pip check
```

These are WSL instructions, not physical Pi instructions. Do not install
`requirements-dev.txt` or the WSL manifest on Pi. ML libraries, tests and developer
tools are not automatic device dependencies. A missing required runtime dependency
must produce an explicit `unavailable`/startup error; starting a service never
installs packages or downloads models. Device runtime changes require a separate
compatibility and rollback plan.

## Hardware and diagnostics

Separate status observation from attempts that open devices. Default diagnostics
read safety/telemetry API, `systemctl show`, `journalctl` and resource owners.
Do not instantiate an SDK for UART observation: the motion executor is its sole
owner. `scripts/diag_sensors.py` and `scripts/sys_xgo-init.py` read executor status
without initializing actuators.

ALSA preflight that opens capture/playback is a hardware trial requiring a prepared
profile and operator decision. Legacy preflight `--force` is not routine diagnosis
or an automatic startup step. With PR03 resource diagnostics, stop the owning task
first:

```bash
python3 scripts/resource_diag.py status mic
python3 scripts/resource_diag.py status camera
python3 scripts/resource_diag.py status uart
```

PR03 manual recovery requires `--force --operator-consent --pid <PID>` for a currently
observed owner. Task leases, UART, LCD and baseline are protected. Observation
failure means `unknown`, not `free`. There is no default killing, SIGKILL or automatic
service resumption. [Resource diagnostics](../resource_diagnostics.md) gives the
precise contract.

## Validation and deployment paths

Check formatting, imports and software tests in WSL with hardware fakes:

```bash
/home/pi/Rider-Pi/.venv/bin/ruff check apps/ common/ services/ scripts/ tests/
/home/pi/Rider-Pi/.venv/bin/ruff format --check apps/ common/ services/ scripts/ tests/
RIDER_PI_CI=1 MOCK_HW=1 RUN_DEVICE_TESTS=0 /home/pi/Rider-Pi/.venv/bin/python -m pytest
git diff --check
```

The pytest command is for the isolated WSL software suite. Physical motion trials
are separate and require consent from the present operator for a specific plan;
they never run inside pytest, CI or a generic diagnostic script. Camera/audio
trials also do not run automatically during diagnosis. The development robot is
powered by a cable; prepare the space and cable before an approved motion trial.

The short DEV path validates changes on hardware before GH publication under the
deployment document and any required physical-trial consent. The release path is:
local Git → remote GH branch → PR/review → merge → pull on the device.
Record the exact version, local overrides and rollback path. A code change never
grants movement permission or changes autostart policy.

[Utility scripts](../ops/utility-scripts.md) ·
[Service management](../ops/systemd-scripts.md) ·
[Safety](../apps/safety.md)
