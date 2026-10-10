# Rider-Pi documentation

Rider-Pi executes robot commands and hosts local robot applications. Rider-PC
provides the operator interface and additional AI processing. Venom is planned
for top-level coordination; its integration is deferred.

## Start here

- [Project vision](../PROJECT.md), [architecture](../ARCHITECTURE.md), [diagrams](../ARCHITECTURE_DIAGRAM.md).
- [Development](development.md), [deployment and recovery](DEPLOYMENT.md).
- [Documentation policy](DOCUMENTATION_POLICY.md), [configuration and secrets policy](config/POLICY.md).
- [Polish documentation](../docs_pl/README.md).

## Interfaces and applications

- [Pi ↔ PC provider contract](OFFLOAD_PROVIDER_PROTOCOL.md).
- [API index](api-specs/README.md), [control](api-specs/control.md), [navigation](api-specs/navigator.md).
- [Application modules](apps/README.md), [hardware drivers](drivers/README.md).
- [Web screens](ui/README.md), [diagnostics and version footer](ui/panel-diagnostics.md).
- [Follow Me tracking](FOLLOW_ME_TRACKING.md), [navigation visualization](NAVIGATION_VISUALIZATION.md).
- [Push-to-talk](PTT_USAGE.md), [voice metrics](voice_metrics.md), [resource diagnostics](resource_diagnostics.md).

## Configuration and operation

- [Configuration index](config/README.md), [voice](config/voice.md), [face](config/face.md), [validation](config/validation.md).
- [WM8960 audio](audio/wm8960.md), [ALSA](config/alsa.md).
- [Scripts](scripts/README.md), [script guides](ops/README.md), [systemd mapping](SYSTEMD_SERVICES_MAPPING.md), [unit catalogue](SYSTEMD_SERVICES_INVENTORY.md).
- [Google Gemini](ecosystem-google.md), [Google Home](google-home-integration.md), [Home command API](google/home_command.md).
- [Quality guards](QUALITY_GUARDS.md), [working agreements](../WORKING-AGREEMENTS.md), [agent instructions](../AGENT.md).
- Releases: [v0.6](release-notes/v0.6.md), [v0.5.3](release-notes/v0.5.3.md), [v0.5.2](release-notes/v0.5.2.md).

Public guides describe the project and its interfaces. Plans, task reports and
results from individual devices remain in ignored local operational directories.

Polish is the starting point; keep English contracts and guides current.
Local plans and reports exist only in `docs_pl/_to_do/` and `docs_pl/_done/`.
