# Environments, dependencies and tests

## Where code runs

The physical Rider-Pi uses the manufacturer image, Python 3.9 and packages
required by its enabled services. WSL runs development and automated tests.
Rider-PC and Venom have separate stacks.

| Scope | Raspberry Pi | Rider-Pi WSL |
| --- | --- | --- |
| Broker, BUS, motion executor | `pyzmq` required | required for transport tests |
| API and panel | Flask/Werkzeug required | required for API tests |
| LCD and rendering | Pillow required | Pillow and a mock LCD |
| Camera, vision, mapping | NumPy/OpenCV for the selected profile | NumPy and headless OpenCV for software tests |
| MediaPipe, ML models, provider SDKs | selected backends only; prefer PC for expensive processing | separate test profiles, explicit external SDK mocks |
| 2D simulator | outside the core runtime; pygame may exist in a legacy splash fallback | pygame required for simulation |
| pytest, coverage, Ruff and test plugins | not a deployment requirement | local WSL/CI tools |

A missing required dependency is an environment preparation error. Do not
change an application contract or mock a required package to avoid installing
it. Hardware and external provider mocks are explicit test scope choices.
A missing optional backend means unavailable functionality, never ready.
`pyzmq` is a required runtime package.

Google OAuth libraries are optional integration dependencies, loaded only
when authentication or token refresh is requested. Their absence does not
prevent the core API from starting; OAuth reports unavailable. They are not
part of the basic WSL test set or an automatic Pi installation.

## Prepare WSL

Reuse the existing Rider-Pi `.venv`, including from worktrees. Do not create
one environment per PR. Install locally, never into global Ubuntu, Venom or
Rider-PC. Reuse the pip cache; do not copy `site-packages` between projects.
Separate stacks may require different versions.

The baseline is `config/agent/requirements-wsl.txt`. Do not automatically
install all of `requirements-dev.txt`: it mixes optional ML and provider
integrations with development tools. Installing declared missing WSL
dependencies is part of preparing the development environment.

```bash
# In Rider-Pi, using the existing interpreter; no sudo and no --upgrade.
.venv/bin/python -m pip install -r config/agent/requirements-wsl.txt
.venv/bin/python -m pip check
.venv/bin/ruff --version
.venv/bin/python -m pytest --collect-only -q
```

`make test-env` checks packages and Ruff. `make test` and `make lint` reuse
the same existing venv from worktrees; a missing venv produces a clear error.
Use `TEST_PY=/path/.venv/bin/python` for another existing Rider-Pi environment
and `TEST_ARGS='-q tests/selected_test.py'` for a focused check.

From a worktree, use absolute paths to that same interpreter and Ruff.
A newer WSL Python does not establish Python 3.9 compatibility; CI checks the
target version. Releases record chosen versions. Constraint files contain
only pip syntax and comments, never assistant instructions.

## Prepare the device

Do not deploy the WSL virtualenv, test packages, caches or models with code.
Check selected profile dependencies in the interpreter used by each unit.
A missing runtime package requires one planned environment change: Python
3.9 and manufacturer compatibility, required profile, memory/disk cost,
installation and rollback. Avoid repeated ad hoc installs after import errors.
Do not remove existing packages merely because they are outside the core.

## Test scope

- Automated software, integration and E2E tests run in WSL/CI with an isolated
  BUS, mocked hardware and no connection to the robot.
- On Pi, run a short, selected hardware check or state read, such as camera,
  LCD or telemetry. Do not move full pytest/coverage suites there.
- Drive, yaw, height, balance, actions and autonomy capable of movement
  require separate operator consent for a concrete manual attempt. Tests,
  diagnostics, deployment and panel loading never invoke them automatically.

Permission to install WSL packages, use a camera or deploy does not arm motion.
See [physical safety](apps/safety.md) and the two code paths in
[deployment](DEPLOYMENT.md).
