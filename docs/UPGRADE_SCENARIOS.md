# Scenario installation migration

The maintained [task/resource contract](TASKS_SERVICES_RESOURCES.md) replaces the historical target-only flow.
Repository source does not prove installed units, readiness or operator motion consent.

1. Read `/svc`, `/api/logic/features`, `/api/services/graph` and the safety state.
2. Run `scripts/systemd-sync.sh` to review a read-only plan.
3. Apply links only when the plan is reviewed: `sudo scripts/systemd-sync.sh --apply`.
   It records backup/manifest and daemon-reloads without changing running processes.
4. Boot ownership consolidation is a separate explicit `--consolidate-boot` decision.
   Preserve network/SSH, boot/splash/LCD and manual Jupyter.
5. Read actual LoadState/ActiveState/SubState/UnitFileState and task members again.
   Missing S6/S7/S10 remains unavailable until linked and observed.
6. Use task API for task start/stop. Optional targets are markers, not task execution.
   Never activate S1/S3/S4/S9 as an automatic smoke check.

S6 is passive. S7 chooses local OR PC vision. S5/S10 selects only the needed domain.
S11 selects one tool; no GUI, legacy face or Jupyter autostart.
Unknown choices are refused, and failed steps cannot become optimistic success.

Automatic validation uses mock systemd/resources/BUS. Physical camera checks are
separate hardware checks; actuator trials are manual only with explicit operator
consent for the exact plan. Camera, migration or deployment consent never implies
permission to move.

Rollback uses the printed backup path:
`sudo scripts/systemd-sync.sh --rollback /etc/systemd/system/_rider_catalog_<stamp>`.
Changed units are not overwritten silently.
