# Systemd scripts

## Catalog and task ownership

All unit allowlists are derived from `common/service_catalog.py`.
Do not add a second shell array. See [tasks, services and resources](../TASKS_SERVICES_RESOURCES.md).

`sys_control.sh UNIT ACTION` accepts catalog units and start/stop/restart/enable/disable.
It acts only on the system manager, without fallback to another scope.
The safety guard requires the matching owner, verified capabilities and written
intent for moving starts. Starting only the sole executor baseline is read only
and creates DISARMED. It does not arm actuators.
Moving stop waits for confirmed STOP; restart never restores consent.
Optional/dev/manual units cannot be enabled through this tool.
Use task API for tasks and shared consumers; privileged shell administration is explicit.

## systemd-sync.sh

The default invocation prints a read-only installation plan.
The catalog contains source units, including S6/S7/S10, but runtime readiness
must be confirmed through `/svc` and `/api/logic/features`.

```bash
./scripts/systemd-sync.sh
sudo ./scripts/systemd-sync.sh --apply
sudo ./scripts/systemd-sync.sh --apply --consolidate-boot
sudo ./scripts/systemd-sync.sh --rollback /etc/systemd/system/_rider_catalog_<stamp>
```

`--apply` links source units, backs up previous files/links and records a manifest,
then daemon-reloads. It does not start/stop/restart a process.
Boot consolidation is a separate opt-in decision: minimal/splash/LCD/Wi-Fi remain
the boot owners; optional and redundant enabled entries are disabled without --now.
No default target, network, SSH, LCD orientation, unrelated unit or drop-in is changed.
`--with-dev` is accepted for compatibility and does not install legacy units.
Rollback refuses to overwrite a unit changed since migration.

Task targets are markers: start a task through its API, not by starting a target
and assuming its members became ready. Existing running units are observed as
base/external consumers; a manager restart does not recreate motion intent.

## Camera guard and recovery

`vision-resource-guard.sh claim|release` performs read-only admission checks.
Claim verifies the existing RAW owner and frame feed for offload; release checks
that offload stopped. It never stops another task or silently restores preview.

`sys_camera-free.sh` requires exact V4L2 paths, current PID, --force and
--operator-consent for a manually reviewed recovery. It never touches SPI/LCD
and never escalates automatically to SIGKILL. Prefer task stop first.
HTTP recovery also refuses consumers and protected UART/LCD/base owners.

## Verification

Automatic checks use isolated fake systemd/resource/BUS fixtures only.
Never use target activation or an actuator trial as a generic migration smoke test.
Physical actuator trials require separate operator consent for the exact plan.
Review application preview and unit migration separately; preserve API/SSH/Wi-Fi,
boot/splash, LCD rotation and manual Jupyter.
