# Utility scripts and diagnostics

Follow the [environment policy](../ENVIRONMENT_POLICY.md) and
[configuration policy](../config/POLICY.md). Observation, hardware trials and
physical motion have separate procedures. Running diagnostics grants no motion
permission.

## Software tests in WSL

`scripts/diag_test-suite.sh` runs selected isolated motion-contract, HTTP and
sandbox tests. It does not open camera, audio, LCD or UART. Reuse the existing venv:

```bash
PYTHON=/home/pi/Rider-Pi/.venv/bin/python scripts/diag_test-suite.sh
RIDER_PI_CI=1 MOCK_HW=1 RUN_DEVICE_TESTS=0 /home/pi/Rider-Pi/.venv/bin/python -m pytest
```

Run the full software suite in WSL. Do not install it on the lightweight Pi and do
not infer read-only behavior from a legacy `diag_*` filename. `diag_tests-audit.sh`
examines the test set. Detection benchmarks are separate tasks for a selected
backend and input; a trial with the actual camera requires an operator decision
and prepared profile.

## Executor and service observation

`diag_motion-status.py`, `diag_sensors.py` and `sys_xgo-init.py` read the single
executor's status. They do not construct another SDK, reset the robot or authorize
actuators. The `sys_xgo-init` name preserves CLI compatibility; it no longer denotes
physical initialization.

```bash
python3 scripts/diag_motion-status.py
systemctl show motion-executor.service -p LoadState -p ActiveState -p SubState -p UnitFileState -p MainPID
journalctl -u motion-executor.service --since "5 min ago" -n 50 --no-pager
curl --fail http://127.0.0.1:8080/api/control/state
```

An active process or transport ACK does not prove physical stop. Safety status
reports permission, generation, STOP confirmation and per-actuator availability.
Uncharacterized hardware capabilities remain unavailable until a separate manual
trial.

`diag_xgo-bootloader.py` is a historically misnamed LCD script: it initializes the
display and changes backlight. It does not observe firmware version or UART.
Do not include it in automatic diagnosis. Preserve `FACE_LCD_ROTATE=270` and the
current startup display sequence.

## Motion and E-STOP

`demo_trajectory.py` disables the former automatic movement sequence.
`manual_motion-probe.py` performs one API trial after a specific plan, current
consent and preparation by the present operator. Never call it from pytest, CI,
deployment or a general test script. The development robot has a power cable;
the operator must prepare the cable and space.

`sys_emergency-stop.py` uses the canonical safety API:

```bash
python3 scripts/sys_emergency-stop.py status
python3 scripts/sys_emergency-stop.py stop
python3 scripts/sys_emergency-stop.py on
```

`stop` revokes permission and requests STOP; `on` latches E-STOP. `off` requires a
separate plan and interactive consent, and leaves the robot DISARMED. It never
opens UART directly or rearms automatically. Inspect `confirmed` and executor ACK,
not merely HTTP status or CLI exit code.
See the [safety contract](../apps/safety.md).

## PR03 services, resources and migration

Observe the catalog, units and resource owners:

```bash
curl --fail http://127.0.0.1:8080/api/logic/catalog
curl --fail http://127.0.0.1:8080/svc
python3 scripts/resource_diag.py status camera
python3 scripts/resource_diag.py status uart
scripts/systemd-sync.sh
```

The catalog and default read-only `systemd-sync` plan belong to PR03; older versions
may not provide them. Check the script version before using legacy `systemd-sync`,
whose former behavior changed the system. Applying a PR03 installation plan
requires explicit `--apply`. Autostart consolidation is a separate
`--consolidate-boot` action. Observation examples authorize neither operation.

Start only the selected task through the catalog UI/API, after checking dependencies
and required devices. Task `requested/starting/ready` differs from service
`ActiveState`. Finishing a movement task requires confirmed STOP before resources
are released. Recovery is manual, for named owners with explicit effects.
Camera recovery never owns UART or SPI/LCD.

`util_export-env.sh` and `util_load-config.sh` configure the current process locally;
do not add global package installation or shared Ubuntu profile changes.
`sys_cleanup.sh` mutates files: inspect its scope before using it separately.
It is not routine diagnosis or a step in every deployment.

[Resource diagnostics](../resource_diagnostics.md) ·
[Systemd management](systemd-scripts.md) ·
[Application modules](../apps/)
