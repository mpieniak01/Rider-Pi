# Pi deployment and recovery

The device has its own Git checkout and local configuration. Update code
through Git over SSH; copying the whole WSL workspace is not the deployment
procedure. Confirm the device checkout path from the service unit before
using it. WSL main, GitHub main and the running device can have different
revisions.

## Application update

Log in using the locally configured host and user. Do not include the
password in the command. In the device checkout:

```bash
git status --short --branch
git rev-parse HEAD
git fetch origin main
git log --oneline HEAD..origin/main
git diff --stat HEAD..origin/main
```

Record the previous revision locally. Continue only with a clean checkout
on main and a reviewed update compatible with the device Python and
dependencies. Preserve local work instead of resetting it.

```bash
git pull --ff-only origin main
```

When backend code changes, restart only its application service:

```bash
sudo systemctl restart rider-api.service
systemctl status rider-api.service --no-pager
curl --max-time 5 http://127.0.0.1:8080/healthz
curl --max-time 5 http://127.0.0.1:8080/api/status/version
```

Compare the returned version with the checked-out commit. Open `/system/`
and `/control`, check network requests and browser errors. Static web files
normally need a browser reload; documentation-only changes need no service
restart. The motion web bridge on `8081` is separate from the panel on `8080`.
Do not send a movement command as a web deployment health check.

Application updates do not include boot targets, vendor boot scripts,
network/SSH/getty settings, graphics startup or broad systemd synchronization.
Do not run `systemd-sync.sh` or `run_boot` as part of a panel update.
Unit or dependency changes require their own reviewed deployment scope.

## Recovery

For an application failure, use the recorded previous revision and review
the diff before switching versions. Preserve device configuration and local
changes, then repeat the application health checks. Avoid a blanket reset
or reinstall for a web error.

After a global system failure, start with the manufacturer's Linux image,
then restore the repository, required packages and local configuration.
A full 1:1 copy of the existing system is not required. Hardware libraries,
pin assignments and boot components from the manufacturer image remain the
baseline; verify them before starting application services. Keep device
inventory and recovery results in local operational notes, without secrets.

See [development](development.md), [systemd mapping](SYSTEMD_SERVICES_MAPPING.md)
and [configuration policy](config/POLICY.md).
