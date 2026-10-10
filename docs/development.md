# Development

Rider-Pi and Rider-PC are separate repositories. A shared VS Code workspace
does not change the terminal directory or the selected Python interpreter.
Run commands from the intended repository and select its environment.

```bash
pwd
git status --short --branch
git fetch origin
git log --oneline HEAD..origin/main
.venv/bin/python --version
.venv/bin/python -m pip check
```

Check uncommitted changes and stashes before updating a checkout. Use
`git pull --ff-only` on a clean main branch; preserve earlier work rather than
resetting it. Use a separate feature branch for application changes and a
focused PR with relevant checks and review. Documentation-only changes can
be committed directly to main when the repository owner requests it.

## Two paths for device work

A small fix can take the short path: local commit → `make pi-preview` →
function test on the Pi. Choose WSL checks for the change; full pytest is
not mandatory for every iteration. Preview happens before push or PR.
Preview the next local commit immediately; `make pi-rollback` restores the base.

Record accepted code through release: push → PR → relevant checks and review
→ merge → `make pi-release PI_COMMIT=<full-main-sha>`.
Reviewed contents must match what was tested on the Pi. See
[deployment](DEPLOYMENT.md) for details, component restart and recovery.

## Configuration and local notes

Use ordinary local env files. `.env`, private `.env.*`, `evn.ssh.local` and
`config/local/` contain developer configuration and credentials. Keep them
out of Git, PR attachments, logs and deployment packages. Public
`.env.example` and `.env.*.example` templates contain placeholders only.
Preserve an existing `.env`; do not overwrite it with a template.

The private SSH file should have mode `600`. Edit credentials locally;
do not put passwords in command arguments or documentation. Standard SSH
does not load `evn.ssh.local` automatically.

Task plans belong in ignored `docs_pl/_to_do/`; completed notes and session
audits belong in ignored `docs_pl/_done/`. These local directories have no
English copy. Publish maintained guides and their
required images according to the [documentation policy](DOCUMENTATION_POLICY.md).
Before committing, review `git diff --cached --name-status` and
`git diff --cached --check`. Do not force-add local files.

## Pi environment and checks

The manufacturer runtime uses Python 3.9 on Raspberry Pi OS / Debian.
A newer WSL interpreter does not establish compatibility with that runtime.
Read [agent instructions](../AGENT.md) and [working agreements](../WORKING-AGREEMENTS.md).
Use existing dependencies; do not install online packages on the Pi as part
of routine application work.

Use Ruff 0.6.9 from an existing environment and run relevant tests directly:

```bash
ruff check .
ruff format --check .
make test TEST_ARGS="-q tests/test_systemd_services.py tests/config/"
.venv/bin/python -m pytest tests/test_version_api.py -q
```

The version endpoint tests require the API dependencies. Hardware, audio,
vision and browser checks have separate prerequisites; choose the scope
required by the change. The commands above are examples, not a mandatory
full set before every preview. Record the revision, command and result in a local
task note. Mocked tests do not verify motors, sensors or physical tracking.

The [Pi dashboard](ui/panel-diagnostics.md) uses port `8080`.
Application work must preserve boot, network and SSH services.
See [deployment and recovery](DEPLOYMENT.md) before updating the device.
