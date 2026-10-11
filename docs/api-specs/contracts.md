# Rider API contracts

This document defines the contract used by Rider-Pi, Rider-PC and the operator screens. Domain data retains its independent version. JSON responses use one small envelope; JPEG, WAV, SVG, Prometheus and SSE retain their native transport.

## Negotiation and compatibility

Request the existing URL with `Accept: application/vnd.rider.api+json;version=1`. The response has the same content type and `Vary: Accept`. An unsupported explicit envelope version returns HTTP 406. Requests without this negotiation receive the documented legacy projection during the Pi then PC rollout. A response contains one domain payload, rather than complete canonical and legacy copies.

Command bodies keep their original generation, sequence, source, request ID, timestamp and TTL. Content-Type application/json remains accepted. A proxy never constructs a fresh safety envelope or retries an ambiguous operation.

```json
{
  "meta": {
    "envelope_version": 1,
    "contract_id": "rider.telemetry",
    "contract_version": 1,
    "host": "pi",
    "source": "motion-executor",
    "observed_at": null,
    "generated_at": 1000.0,
    "server_time": 1000.0,
    "stale": false,
    "offline": false,
    "partial": true
  },
  "ok": true,
  "data": {},
  "error": null,
  "operation": null
}
```

`observed_at` belongs to the producer observation. It is null for mixed snapshots or unknown source time. `generated_at` and `server_time` describe the response. Neither refreshes a cached sensor, navigation object or frame. PC adds `meta.transport` with receiver_host, received_at, attempted_at and upstream_status, preserving the Pi source metadata.

For a read, ok describes whether the requested projection was obtained. One failed sensor makes the result partial and remains visible alongside healthy channels. It does not prove all hardware is ready. Transport failure invalidates cached presentation without replacing its original times. Zero and false remain valid values; missing or unknown values remain null.

Errors have `code`, `message`, `retryable` and optional bounded `details`. Safety errors retain their specific rejection code.

## Domain families

| Contract | Version | Data |
| --- | --- | --- |
| rider.safety | 1 | DISARMED/ARMED/ESTOP, owner/lease, generation/instance, capabilities, target/output, SDK observations, sensor_quality and ACK |
| rider.telemetry | 1 | devices and independent XGO observations, firmware, camera/LCD state |
| rider.system | 1 | CPU/load, memory/disk, OS, temperature, uptime and history |
| rider.health | 1 | API liveness, BUS observation and component readiness |
| rider.catalog / rider.tasks | 2 | units/features, options, requested/running/ready, resources, start availability and evidence |
| rider.services / rider.service_graph | 2 | systemd rows, host-qualified identities and edges |
| rider.resources | 1 | physical/logical resource, diagnostic availability, free true/false/null, owners and recovery evidence |
| rider.frames / rider.obstacle | 1 | distinct RAW/PROC/SSD/OBST/TRACKER observations and obstacle/ROI ratios |
| rider.navigation / rider.odometry / rider.calibration | 1 | original observations, matching coordinate frame/HOME/profile and configuration confirmations |
| rider.providers / rider.models | 1 | requested/effective routing by domain and model inventory |
| rider.voice / rider.chat / rider.face | 1 | explicit domain result, backend, source, readiness and error |
| rider.google_feed / rider.home | 1 | cached feed, auth/devices and explicit cloud commands |
| rider.api_metrics / rider.version | 1 | counters and genuine code revision |
| rider.network / rider.mcp / rider.project / rider.knowledge / rider.assistant | 1, PC | preserved local endpoint payload and explicit result |

The domain version is not the envelope version. A resources body may retain a legacy catalog contract_version while its envelope identifies the resources domain independently. New schemas require a named migration and fixtures.

## Measurement observations

XGO uses `sensor_quality.sensors.{roll,pitch,yaw,battery}`. Every channel has its own value, unit, source, observed_at, max_age_s, ready, stale, offline, error, instance_id/generation when supplied, simulated flag and physical_validity. Shared code handles all channels and screens. assessed_at pairs with age_s and denotes assessment only; adding producer publication age to an API-recomputed age is forbidden.

- Battery canonical value is a ratio in [0,1]. REST legacy battery_pct is percent: 1 means 1%, converted to .01. The older devices.xgo BUS ratio is identified by topic/schema; it is not inferred from the numeric magnitude.
- SDK roll/pitch/yaw use sdk_raw with physical_validity unverified. Legacy wrapped yaw is explicitly display_only with legacy_wrap_180 derivation; it is not navigation heading. A null raw yaw never silently falls back to wrapped yaw.
- CPU, memory and disk utilization use percent [0,100]. Existing memory _mb fields mean MiB and disk _gb fields mean GiB. Load averages are dimensionless.
- Obstacle edge_ratio, edge_ratio_raw, ROI bins and thresholds use ratios [0,1]. Legacy edge_pct aliases retain their established ratio meaning.
- Navigation positions use metres and theta uses radians. Calibration tables use m/s and rad/s with signed steps.
- Original channel time may not be replaced by parent publication, cache reception, SSE delivery or HTTP response. Clock correction uses the conservative server_time bound.
- A missing axis does not invalidate a fresh battery. Simulation does not establish real device readiness. Firmware is cached metadata and cannot prove liveness.

## Operations and physical safety

operation carries request_id, action, target, status, confirmed, ack_kind, ack, actuation and physical_completion. HTTP 202 stays pending. Observed software effect or a matching terminal domain ACK is required for executed/confirmed; accepted transport or SDK does not prove physical completion. Partial remains partial; timeout is unknown and is never retried automatically.

`process_running`, `ready`, `can_move`, `start_available` and per-action permissions represent different facts. Start-unavailable is rejected before systemd, journal or BUS mutation. Starting the base executor in DISARMED does not authorize motion. Passive S6 planning retains its own mode and does not become a movement task.

GET and HEAD never operate actuators, start capture, acquire resources or change the safety generation. Historical GET /api/stop is replaced by POST; the GET method cannot send STOP. All original command identity and freshness fields survive every proxy.

A single executor owns UART. Canonical `motion.command`, `motion.state` and `motion.ack` retain safety-v1. Older motion producers must migrate or be explicitly unavailable; no adapter may invent authority, sign or timestamp. IMU observation is independent of motor completion. Autonomy stays blocked until the separate manual physical work establishes its required evidence.

Calibration save, requested activation, matching applied motion+odometry state and physical model readiness are separate states. Profile/reference/HOME changes invalidate old frame geometry. A passive plan requires fresh matching frame data and never establishes traversal readiness.

Automated WSL tests use isolated mocks. Real device acceptance reads data with ESTOP and zero output. Physical motion trials require separate explicit operator consent. Device profiles and measurements remain local configuration.

## Service and resource schema

The canonical service row has identity=host:unit, host, unit, load_state, active_state, sub_state, unit_file_state, pid, process_running, consumers/dependencies, resources, source/time, error and permissions where available. A task member Boolean active maps to process_running; it cannot be treated as systemd ActiveState.

Resource free is null when observation is unavailable. Logical resources declare diagnostic_available=false. UART/LCD recovery preserves their protected ownership policy. Sending SIGTERM is pending release until a new owner/resource observation confirms release.

Provider requested/effective routing is per domain. Peer reachable does not prove model initialized/loaded/ready. Persistence failures remain errors. Model inventory does not invent latency or resource utilization, load models, install packages, or offer unsupported operations.

## Frames and history

RAW, PROC, SSD, OBST and TRACKER have separate source, kind/stream, URL, frame identity, original capture/observation time or null, file_observed_at with explicit file_mtime provenance, exists, stale, error, placeholder and max_age_s. Metadata and image use one resolver. PC OBST uses obst_annot; SSD remains separately available.

Archived files and repeated JPEG delivery do not prove a live producer. Current previews display fresh observations and never start capture. An explicitly requested archive is clearly marked. /api/last_frame is binary image data.

All existing charts and cards remain. History is bounded, with its real time span or label 'last 60 samples'; 60 samples polled every two seconds are not labelled 60 seconds. Stale/missing samples create gaps. ROI scaling preserves ratios. LCD remains mounted sideways with compensation 270 degrees.

## Implementation and acceptance

Pi centralizes negotiation, route/domain mapping and observation production. Each browser uses one decoder and one measurement helper. PC negotiates once through RestAdapter, preserves metadata and original command bodies, and uses bounded BUS caches with actual ZMQ prefixes and SSE fanout.

The checked-in `tests/fixtures/contracts/rider-v1.json` is identical in both repositories and contains synthetic healthy/partial, pending/rejected, unknown-time, cache failure, services, frames and legacy unit cases. It contains no physical measurements.

Acceptance checks the API, all existing cards/charts/previews and remaining pages with actual data after isolated WSL tests. Deploy both local scopes to Pi/PC preview first; publish to GitHub afterward. Heavy test dependencies stay in existing WSL environments. Protected driver/UART/unit changes use the separate existing migration procedure, with no reboot or motion.

The Polish [contracts specification](../../docs_pl/api-specs/contracts.md) includes the field mappings, endpoint and screen inventories. The route inventory lists definitions, including optional/separate-port applications; it is not evidence that every optional service is enabled. Compare it with the instantiated route registry during verification.



## Registered endpoint inventory

Generated from the instantiated main Flask app without hardware or runtime startup. Separate bridge8081 and optional voice services are independently deployed interfaces; native binary/SSE/Prometheus routes retain their MIME. Registration does not prove optional provider readiness.

| Methods | Path | Handler | Domain | Version |
| --- | --- | --- | --- | --- |
| GET, HEAD, OPTIONS | `/` | `dashboard` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/api/app-metrics` | `app_metrics` | `rider.api_metrics` | 1 |
| GET, HEAD, OPTIONS | `/api/bus/health` | `_bus_health` | `rider.health` | 1 |
| OPTIONS, POST | `/api/calibration/activate` | `activate` | `rider.calibration` | 1 |
| GET, HEAD, OPTIONS, POST | `/api/calibration/profiles` | `catalog` | `rider.calibration` | 1 |
| GET, HEAD, OPTIONS | `/api/calibration/profiles/<digest>` | `profile` | `rider.calibration` | 1 |
| GET, HEAD, OPTIONS | `/api/calibration/state` | `state` | `rider.calibration` | 1 |
| OPTIONS, POST | `/api/chat` | `chat_send` | `rider.chat` | 1 |
| GET, HEAD, OPTIONS | `/api/chat/history` | `chat_history` | `rider.chat` | 1 |
| GET, HEAD, OPTIONS | `/api/chat/ping` | `_chat_ping` | `rider.chat` | 1 |
| OPTIONS, POST | `/api/chat/send` | `chat_send` | `rider.chat` | 1 |
| OPTIONS, POST | `/api/cmd` | `control_proxy_handler` | `rider.safety` | 1 |
| OPTIONS, POST | `/api/control` | `control_proxy_handler` | `rider.safety` | 1 |
| OPTIONS, POST | `/api/control/balance` | `api_balance` | `rider.safety` | 1 |
| OPTIONS, POST | `/api/control/height` | `api_height` | `rider.safety` | 1 |
| GET, HEAD, OPTIONS | `/api/control/state` | `api_control_state` | `rider.safety` | 1 |
| OPTIONS, POST | `/api/control_legacy` | `api_control_legacy` | `rider.safety` | 1 |
| OPTIONS, POST | `/api/draw/face` | `draw_face_route` | `rider.face` | 1 |
| OPTIONS, POST | `/api/draw/face` | `api_draw_face_legacy` | `rider.face` | 1 |
| GET, HEAD, OPTIONS | `/api/flags` | `api_flags_get` | `rider.safety` | 1 |
| OPTIONS, POST | `/api/flags/<name>/<state>` | `api_flags_set` | `rider.safety` | 1 |
| GET, HEAD, OPTIONS | `/api/google/raw/last.json` | `google_proxy.get_last_snapshot` | `rider.google_feed` | 1 |
| GET, HEAD, OPTIONS | `/api/google/status` | `google_proxy.get_status` | `rider.google_feed` | 1 |
| OPTIONS, POST | `/api/home/auth` | `home_auth` | `rider.home` | 1 |
| GET, HEAD, OPTIONS | `/api/home/auth/url` | `home_auth_url` | `rider.home` | 1 |
| OPTIONS, POST | `/api/home/command` | `home_command` | `rider.home` | 1 |
| GET, HEAD, OPTIONS | `/api/home/devices` | `home_devices` | `rider.home` | 1 |
| GET, HEAD, OPTIONS | `/api/home/status` | `home_status` | `rider.home` | 1 |
| GET, HEAD, OPTIONS | `/api/last_frame` | `_api_last_frame` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/api/logic/catalog` | `feature_catalog_handler` | `rider.catalog` | 2 |
| OPTIONS, POST | `/api/logic/feature/<name>` | `feature_handler` | `rider.tasks` | 2 |
| GET, HEAD, OPTIONS | `/api/logic/features` | `feature_registry_handler` | `rider.tasks` | 2 |
| GET, HEAD, OPTIONS | `/api/logic/state` | `feature_state_handler` | `rider.tasks` | 2 |
| GET, HEAD, OPTIONS | `/api/logic/summary` | `feature_summary_handler` | `rider.tasks` | 2 |
| GET, HEAD, OPTIONS | `/api/models/installed` | `installed_models_handler` | `rider.models` | 1 |
| GET, HEAD, OPTIONS | `/api/motion/queue` | `api_motion_queue` | `rider.safety` | 1 |
| OPTIONS, POST | `/api/navigator/config` | `api_navigator_config` | `rider.navigation` | 1 |
| OPTIONS, POST | `/api/navigator/return_home` | `api_navigator_return_home` | `rider.navigation` | 1 |
| OPTIONS, POST | `/api/navigator/start` | `api_navigator_start` | `rider.navigation` | 1 |
| GET, HEAD, OPTIONS | `/api/navigator/status` | `api_navigator_status` | `rider.navigation` | 1 |
| OPTIONS, POST | `/api/navigator/stop` | `api_navigator_stop` | `rider.navigation` | 1 |
| OPTIONS, POST | `/api/odometry/reference` | `operator_reference` | `rider.odometry` | 1 |
| GET, HEAD, OPTIONS | `/api/odometry/state` | `reference_state` | `rider.odometry` | 1 |
| GET, HEAD, OPTIONS, PATCH | `/api/providers/<domain>` | `provider_domain_handler` | `rider.providers` | 1 |
| GET, HEAD, OPTIONS | `/api/providers/health` | `providers_health_handler` | `rider.providers` | 1 |
| OPTIONS, POST | `/api/providers/pc-heartbeat` | `providers_pc_heartbeat_handler` | `rider.providers` | 1 |
| GET, HEAD, OPTIONS | `/api/providers/state` | `providers_state_handler` | `rider.providers` | 1 |
| GET, HEAD, OPTIONS, POST | `/api/resource/<name>` | `api_resource` | `rider.resources` | 1 |
| GET, HEAD, OPTIONS, POST | `/api/safety` | `api_safety` | `rider.safety` | 1 |
| GET, HEAD, OPTIONS | `/api/services/<unit>/logs` | `service_logs` | `rider.services` | 2 |
| GET, HEAD, OPTIONS | `/api/services/graph` | `services_dashboard.services_graph` | `rider.service_graph` | 2 |
| GET, HEAD, OPTIONS | `/api/status/version` | `version.version_info` | `rider.version` | 1 |
| GET, HEAD, OPTIONS, POST, PUT | `/api/system/ai-mode` | `ai_mode_handler` | `rider.providers` | 1 |
| GET, HEAD, OPTIONS | `/api/vision/cam` | `vision_api_alias.vision_cam` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/api/vision/edge` | `vision_api_alias.vision_edge` | `rider.frames` | 1 |
| OPTIONS, POST | `/api/vision/follow/face` | `vision_api_alias.legacy_follow_face` | `rider.tasks` | 2 |
| OPTIONS, POST | `/api/vision/follow/hand` | `vision_api_alias.legacy_follow_hand` | `rider.tasks` | 2 |
| GET, HEAD, OPTIONS | `/api/vision/obst` | `vision_api_alias.vision_obst` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/api/vision/obstacle` | `vision_api_alias.vision_obstacle` | `rider.obstacle` | 1 |
| GET, HEAD, OPTIONS | `/api/vision/snap-info` | `vision_api_alias.snap_info` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/api/vision/ssd` | `vision_api_alias.vision_ssd` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/api/vision/tracker` | `vision_api_alias.vision_tracker` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS, POST | `/api/vision/tracking/mode` | `vision_api_alias.set_tracking_mode` | `rider.tasks` | 2 |
| OPTIONS, POST | `/api/voice/asr` | `asr_local_handler` | `rider.voice` | 1 |
| OPTIONS, POST | `/api/voice/capture` | `capture_handler` | `rider.voice` | 1 |
| GET, HEAD, OPTIONS | `/api/voice/providers` | `providers_list_handler` | `rider.voice` | 1 |
| OPTIONS, POST | `/api/voice/providers/test` | `providers_test_handler` | `rider.voice` | 1 |
| OPTIONS, POST | `/api/voice/say` | `say_handler` | `rider.voice` | 1 |
| OPTIONS, POST | `/api/voice/tts` | `tts_local_handler` | `rider.voice` | 1 |
| GET, HEAD, OPTIONS | `/calibration` | `page` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/camera/last` | `camera_last` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/camera/placeholder` | `camera_placeholder` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/camera/proc` | `camera_proc` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/camera/raw` | `camera_raw` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/chat` | `serve_chat` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/control` | `control_page` | `rider.safety` | 1 |
| GET, HEAD, OPTIONS | `/devices` | `devices_page` | `rider.http` | 1 |
| OPTIONS, POST | `/draw/face` | `draw_face_route` | `rider.face` | 1 |
| GET, HEAD, OPTIONS | `/events` | `events` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/face/ping` | `face_ping` | `rider.face` | 1 |
| OPTIONS, POST | `/face/play` | `face_play` | `rider.face` | 1 |
| OPTIONS, POST | `/face/render` | `face_render` | `rider.face` | 1 |
| GET, HEAD, OPTIONS | `/face/state` | `face_state` | `rider.face` | 1 |
| OPTIONS, POST | `/face/stop` | `face_stop` | `rider.face` | 1 |
| GET, HEAD, OPTIONS | `/google_home` | `serve_google_home` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/health` | `health_alias` | `rider.health` | 1 |
| GET, HEAD, OPTIONS | `/healthz` | `healthz` | `rider.health` | 1 |
| GET, HEAD, OPTIONS | `/home` | `serve_home` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/livez` | `livez` | `rider.health` | 1 |
| GET, HEAD, OPTIONS | `/metrics` | `metrics` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/navigation` | `serve_navigation` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/readyz` | `readyz` | `rider.health` | 1 |
| GET, HEAD, OPTIONS | `/snapshots/<path:fname>` | `snapshots_static` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/state` | `state_route` | `rider.telemetry` | 1 |
| GET, HEAD, OPTIONS | `/static/<path:filename>` | `static` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/svc` | `svc_list_route` | `rider.services` | 2 |
| GET, HEAD, OPTIONS, POST | `/svc/<name>` | `svc_name_route` | `rider.services` | 2 |
| GET, HEAD, OPTIONS | `/svc/<name>/status` | `svc_status` | `rider.services` | 2 |
| GET, HEAD, OPTIONS | `/sysinfo` | `sysinfo` | `rider.system` | 1 |
| GET, HEAD, OPTIONS | `/system/` | `system_dashboard_html` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/view` | `dashboard` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/vision/cam` | `vision_api.vision_cam` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/vision/edge` | `vision_api.vision_edge` | `rider.frames` | 1 |
| OPTIONS, POST | `/vision/follow/face` | `vision_api.legacy_follow_face` | `rider.tasks` | 2 |
| OPTIONS, POST | `/vision/follow/hand` | `vision_api.legacy_follow_hand` | `rider.tasks` | 2 |
| GET, HEAD, OPTIONS | `/vision/obst` | `vision_api.vision_obst` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/vision/obstacle` | `vision_api.vision_obstacle` | `rider.obstacle` | 1 |
| GET, HEAD, OPTIONS | `/vision/snap-info` | `vision_api.snap_info` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/vision/ssd` | `vision_api.vision_ssd` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/vision/tracker` | `vision_api.vision_tracker` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS, POST | `/vision/tracking/mode` | `vision_api.set_tracking_mode` | `rider.tasks` | 2 |
| GET, HEAD, OPTIONS | `/web/<path:fname>` | `serve_web` | `rider.http` | 1 |

LCD deployment includes protected boot files and unit defaults; use a separately recorded controlled deployment with backups. Do not force ordinary pi-preview guards or replay the boot vendor cleanup for testing. KEEP_BL_ON defaults to0; LCD idle policy is45s. Battery is unknown before a fresh executor observation exists. The early splash precedes the broker and has no executor measurement yet. After the executor starts, LCD reuses the existing Device Info screen with IP and battery, preserves270-degree orientation and turns off after45s. It introduces no task panel. Acceptance uses this existing display without reboot or movement.

`configured_rot` comes from the API process `PREVIEW_ROT` configuration (default0); it describes preview configuration, not the mounted startup display. The startup renderer reports `rot=270`. Headless camera configuration cannot replace this observation or confirm backlight power.

LCD `preview_config` has its own source time. Actual LCD `source`/`observed_at` describe the renderer lifecycle report; `power_source`/`power_observed_at` require explicit `power_known=true` and `control_write_accepted`. `frame_source`/`frame_observed_at` retain the original report accepting the submitted pixels; an idle/OFF report does not restamp them or the battery measurement. Software acceptance leaves physical visibility unverified; operator confirmation is a separate acceptance record.


## Motion panel scope
- Overview, Devices and Chat expose observations and non-actuating operations, without motion consent forms or STOP shortcuts. Their state observer may provide measurements but does not send commands on focus loss.
- Navigation remains a passive visualizer without an ARM form. Its task catalog shows only non-actuating tasks. Autonomous motion remains unavailable pending manual characterization.
- Control and Calibration require local consent, a short lease, STOP, the correct owner and fresh state for actuator operations.
- System opens as diagnostics. Consent and STOP controls appear after enabling administration because starting/restarting some services can actuate the robot.
- Clearing ESTOP requires an explicit operator plan and consent. It ends in DISARMED and never automatically arms. ARM requires renewed consent.
- Contract negotiation and state refresh finish before constructing the 500 ms command envelope. Existing commands are never restamped or automatically retried.
- Command time uses a separate estimate from the Pi safety response. Observations from other hosts cannot change this estimate.


## Manual control and response tuning

The main calibration view provides the camera, direction arrows, STOP, travel/turn
speed sliders and response ramps. Click duration is an advanced setting.
Speed sliders select the next manual trial; ramps apply only after saving and
explicit activation. Manual control uses the single global arm/disarm button;
there is no additional per-arrow consent. Reading, sliders, save, apply and rollback never start movement.
There are no automatic repeats or calibration sequences.

The optional profile object interaction contains linear_speed, turn_speed (0–1)
and pulse_duration (0.01–0.25 s). Both clients read shared Pi settings from
motion.calibration.interaction. They do not grant motion authority.
Legacy profiles remain readable. Existing motion ramps and executor ceilings
stay authoritative. Application still needs both consumer confirmations;
manual response tuning does not require measured odometry or HOME.

Mapping rider-1.4.2-levels-v2 reports signed linear_step command levels in
−127..127, converted to native SDK input by level * 1.5 / 127.
Signed turn_step is −70..70 and corresponds to native SDK turn input.
motion.output.units is command_levels; mapping_id, linear_sdk_value and
turn_sdk_value describe commands, never measured velocity or wheel encoders.
The guarded write hook rounds around protocol neutral 128, including STOP;
the installed vendor library is not modified. Pulse duration bounds time;
command magnitude bounds requested speed.
Measured odometry requires matching conditions.command_mapping.
Old measurements remain inspectable but cannot verify the changed mapping.
Coefficients are never converted automatically.

Measurement tables, pose/HOME, import and detailed observations are advanced
facilities. Operator judgement tunes manual control without verifying metric
odometry or enabling autonomy.

## Global panel arming and separate test permission

The single button on the right displays the confirmed executor state:
red "Robot disarmed", green "Robot armed". Clicking red grants manual panel
permission; clicking green sends STOP. Clearing software ESTOP and ARM follow
one explicit click, sequentially, only after a fresh DISARMED confirmation.
External ESTOP, unavailable hardware, an unconfirmed clock or a missing
confirmation still block ARM. Arming does not move the robot. The panel uses arming_mode=operator: permission remains until operator STOP
or disarming, without a timer or automatic renewal. Changing views does not send STOP.

The safety contract adds execution_context (panel/test), panel_motion_enabled
and test_motion_enabled. The panel sends execution_context=panel. Panel consent
cannot authorize test commands, even with test_operator_consent=true.
A manual physical probe uses its own execution_context=test session and explicit
test_operator_consent=true at ARM and every motion attempt. A test session cannot
authorize panel controls. A single executor session prevents simultaneous control.
STOP invalidates both flags.

Automated pytest/CI remains isolated: real SDK, hardware devices, SSH and robot
network access are blocked independently of either flag. Test consent does not
disable isolation. manual_motion-probe.py requires a present operator, an
interactive terminal and a one-time typed approval; it sends STOP after the probe.

Panel: arming_mode=operator, lease_remaining_s=null. View and focus changes do not disarm. Physical test sessions remain timed with separate consent. Hardware faults and external ESTOP still stop the executor; stale data blocks new commands.

A bounded panel movement pulse stops the drive when it ends, while operator arming remains active for the next click. STOP/disarm revokes the session; test sessions keep their timeout behavior.
