# Rider-Pi HTTP API

[Unified Pi/PC contracts](contracts.md) describe negotiated v1 envelopes.
Examples without negotiation use the legacy projection. API contract version,
payload schema, settings revision and command generation are separate.

The main service is rider-api.service, entry point
[services/api_server.py](../../services/api_server.py), on port 8080.
The [HTTP boundary](security.md) applies before handlers: same-origin browsers
are supported, additional origins require RIDER_ALLOWED_ORIGINS, and trusted
host configuration is independent of authentication. Foreign origins are
rejected, including OPTIONS. Nonempty mutations require JSON except the
documented binary-upload routes. There is no unrestricted wildcard CORS.

## Interfaces

| Area | Endpoints or guide |
| --- | --- |
| Health and status | GET /healthz, /api/status, /api/safety, /api/control/state, /api/status/version |
| Motion and safety | [Control](control.md), [manual intent and descriptors](manual-motion.md), [panel ownership](../manual-panel-authority.md) |
| Calibration | GET/POST /api/calibration/controls; [settings and profiles](../apps/calibration.md) |
| Local navigation | /api/navigator/*; [navigator](navigator.md), distinct from the Venom loop |
| Venom navigation | /api/navigation/config, /status, /trial, /journey; [directional contract](../DIRECTIONAL_NAVIGATION.md), [journey](../AUTOMAT2_JOURNEY_V1.md) |
| Profiles and model selection | /api/navigation/models, /local-models, /model, /model-selection; [models](../apps/perception-models.md), [policy parameters](../vision-policy-parameters.md) |
| Visual measurement | GET/POST /api/navigation/image-reference; [independent visual reference](../IMAGE_REFERENCE.md) |
| Camera lifecycle | /api/resource/camera/pipeline; [pipeline](../CAMERA_PIPELINE_V1.md), [source OFF](../apps/camera-source-off.md) |
| Remote compute | /api/compute/config, /status, /tasks/<task>; [Venom pairing](../COMPUTE_VENOM.md), [provider contract](../OFFLOAD_PROVIDER_PROTOCOL.md) |
| Agent pulse and prepared speech | /api/control/agent/state, /pulse, /api/voice/playback, /cancel; [private bearer contract](../apps/agent-control.md) |
| Operator tasks and resources | [Operator control](../OPERATOR_CONTROL_V1.md), [resources](../RESOURCE_ARCHITECTURE.md) |

Table entries with a shared prefix abbreviate full route names, not additional
root endpoints. Read/state GETs do not grant motion permission. The trial and
journey POST routes are explicit actions, not passive status endpoints.
API registration is split across api_core modules; optional capabilities and
current executor state determine availability.

## Application metrics

GET /api/app-metrics returns interactive endpoint counters: metrics keyed by
control, navigator, voice, google_home, chat and face, plus total_errors.
Each group has ok/error counts. These counters are not physical completion,
readiness or a security verdict. They do not replace fresh executor state.

## Responses and time

Use the negotiated response contract for new clients; legacy JSON shapes vary
by endpoint and must not be assumed to be one universal {ok,data} format.
Operation confirmation distinguishes persistence, task activity and SDK
submission. SDK acceptance does not establish physical completion.

server_time helps align command time. observed_at/capture timestamps describe
the actual observation; HTTP receive time cannot replace them. Monotonic times
belong to their own process/host clock domain.

## Media, files and BUS

The API serves the [operator pages](../ui/README.md). Managed camera frames and
streams retain source identity and freshness; a static JPEG is not proof of a
live producer. File serving is confined to configured roots, not arbitrary paths.
See [HTTP/file restrictions](security.md).

Handlers may publish on the internal ZMQ BUS through
[common/bus.py](../../common/bus.py). A successful publish is not a terminal ACK.
[Motion authority](../apps/motion.md) remains on Pi, with current generation,
sequence, TTL, owner and settings revision checked by the executor.
