# Pi deployment and recovery

The device has its own Git checkout and local configuration. Update code
through Git over SSH; copying the whole WSL workspace is not the deployment
procedure. Confirm the device checkout path from the service unit before
using it. WSL main, GitHub main and the running device can have different
revisions.

## Two paths

| Path | Order | Use |
| --- | --- | --- |
| Short | local change and commit → Pi preview → function test | small fixes and hardware iterations before publication |
| Release | push → PR → checks and review → merge → Pi update | record accepted code on GitHub and the device |

Develop in WSL on a feature branch. Choose WSL checks for the change; the full
suite is not a prerequisite for every short iteration. Confirm hardware
behavior on the Pi. `scripts/dev_pi-deploy.py` uses existing Git, SSH and the
Python standard library. It reads the local `evn.ssh.local` file with mode
`600`; the password is excluded from process arguments and the bundle.

## Short path: preview and test on the Pi

The development robot may be on a power cable. Preview and application restarts
do not disarm movement or autonomy. Use reads and mocks for panel changes.
Before driving, turning, height or balance tests, describe the test and obtain
confirmation of free space, a stable surface and safe cable routing. Check the
active executor's actual guards; one ENV flag does not confirm all of them.
See [robot safety](apps/safety.md) for the procedure and limitations.

Before the first preview, device `main` and the local feature branch base
must identify the same commit. Commit selected changes locally in WSL;
neither a push nor a PR is required. From the Rider-Pi checkout:

```bash
git switch -c codex/short-description
# edit; optionally run a short check or relevant WSL test
git add <explicit-file-list>
git commit -m "fix(scope): describe the change"
make pi-preview
make pi-preview-status
```

Preview transfers a Git increment over SSH, checks changed Python syntax
using the device interpreter and switches the Pi to `rider-preview/<hash>`.
Previous `main` remains the rollback point. For each correction, create a
new local commit and run `make pi-preview` again. Do not `git pull` in preview.
The commit and branch identify the complete file set; footer metadata has
a 60-second cache.

For API backend changes:

```bash
make pi-preview PI_DEPLOY_ARGS='--restart-api'
```

This restarts only `rider-api.service` and checks HTTP health. Reload the
browser for static web changes. Each iteration requests API restart explicitly;
a previous restart does not force another restart for web-only changes.
For another application service, choose its
restart and test according to the changed component. Preview does not prove
hardware behavior. Avoid simultaneous processes sharing UART, LCD, camera
or audio.

Return to the previous `main`:

```bash
make pi-rollback
```

Rollback restores the recorded commit. If preview restarted the API,
rollback also restarts it and checks health. Preview branches retain history.
A dirty checkout, local file collision or unexpected state stops deployment.
Preserve earlier work rather than resetting it.

## Release path: PR, merge and Pi update

After accepting the function on the Pi, push the branch, open a PR and run
required checks. Collect naturally arriving reviews without invoking or repeating
them. Missing optional reviews do not block release. Preview valid review fixes when they change
tested code. After merging, use the full `main` SHA:

```bash
git switch main
git pull --ff-only origin main
make pi-release PI_COMMIT=<full-main-sha-after-merge>
make pi-preview-status
```

The tool fetches device `origin/main`, verifies the expected SHA and updates
`main` by fast-forward only. Active preview and release must have identical
file trees; squash merging may change the commit SHA. Changed contents
require another preview. An accepted `main` can also be released directly
without an active preview. `.git/rider-last-release.json` records the prior
revision. For API changes, add `PI_DEPLOY_ARGS='--restart-api'`; restart is explicit.
Releasing identical code already running in preview does not inherit API restart.

Compare Git, `/api/status/version` and `/healthz`, then verify the changed
function. The panel uses `8080`; the separate motion bridge uses `8081`.
Do not use movement as a web deployment health check. Rider-PC code runs
in its existing WSL environment (`make start-dev` in Rider-PC); test its
integration with the Pi while keeping PC packages and models on the PC.

Both paths preserve local configuration, runtime and the display orientation
described in [architecture](../ARCHITECTURE.md#physical-lcd-orientation).
The tool rejects private env files, `config/local/`, runtime data and local
notes, including files added and later removed within bundled history.
Systemd units, drivers, boot and dependencies require a separate deployment
scope. Do not run `systemd-sync.sh` or `run_boot` during a panel update.

## Jupyter autostart migration

After installing the manual Jupyter unit, inspect its existing target links.
For the old link confirmed in `multi-user.target.wants`:

```bash
sudo systemctl stop jupyter.service
sudo rm -f /etc/systemd/system/multi-user.target.wants/jupyter.service
sudo systemctl daemon-reload
systemctl show jupyter.service -p ActiveState -p UnitFileState
```

Keep `/etc/systemd/system/jupyter.service` pointing to the checkout. Running
`systemctl disable` also removes this definition link because its target is
outside systemd's unit search path. The resulting `linked` state is correct:
the unit remains available for manual start without target membership.
Also confirm no other `.wants`/`.requires` links, no vendor cleanup start and
no DEV dependency. Keep Jupyter Lab installed.

## Recovery

For an application failure, use the recorded previous revision and review
the diff before switching versions. Preserve device configuration and local
changes, then repeat the application health checks. Avoid a blanket reset
or reinstall for a web error.

`make pi-rollback` applies to an active preview. After release, read the prior
commit from device `.git/rider-last-release.json`. In a clean checkout, return
to it with `git switch --detach <previous-sha>`, restart only the changed
service and repeat its checks. Released `main` remains in Git; establish
the next base explicitly before another increment.

After a global system failure, start with the manufacturer's Linux image,
then restore the repository, required packages and local configuration.
A full 1:1 copy of the existing system is not required. Hardware libraries,
pin assignments and boot components from the manufacturer image remain the
baseline; verify them before starting application services. Keep device
inventory and recovery results in local operational notes, without secrets.

See [development](development.md), [systemd mapping](SYSTEMD_SERVICES_MAPPING.md)
and [configuration policy](config/POLICY.md).


## Incremental transfer and elapsed time

make pi-preview reads the device commit and sends only new commits since the
last preview, retaining original main as the rollback point. A device revision
change between preflight and deployment stops the operation.
Repeating the same commit transfers no bundle and does not switch branches.
Results include elapsed_s, transfer_bytes and actual changed files.
Separate pi-preview-status is only needed for diagnosis.
Rollback remembers whether any iteration restarted the API; web changes
do not inherit previous restarts.

## Explicit motion preview

For executor updates including drivers/xgo/adapter.py use the preview command
with --restart-api --restart-motion. This scope permits only that adapter among
protected drivers. Stop executor before checkout, restart disarmed, then restart
API. No reboot, automatic ARM, movement trial or GH publication. Rollback remembers
the executor restart. Settings remain outside checkout.

## Development dependency removals

The deployment helper permits package removals and comment changes in
`requirements-dev.txt`, with content validation for each preview commit and the
release diff. It does not install or uninstall packages. New dependencies, version
changes and removed pip options/constraints still require a separate environment
plan; runtime requirements remain protected.
