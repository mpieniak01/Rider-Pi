# Rider-Pi web interfaces

The [operator panel](operator-panel.md) is the current interface and describes
safety, task preparation, device ownership, polling and acknowledgements.

| Route | Purpose |
| --- | --- |
| /view, / | Overview: connection, battery, freshness, tasks and blocks |
| /control | One task catalog, explicit motion consent and requests/ACK |
| /devices | Camera, audio, LCD, UART, owners and consumers; preview on demand |
| /system | Service observations; explicit administration and separate autostart |
| /calibration | Shared directional settings, command curves, profiles and manual trials |
| /navigation | Map/pose/path freshness, explicit trials/journeys, stationary policy configuration and separate visual references |
| /chat | Text and optional TTS, only the required domain prepared on send |

The menu supports Polish and English. Language and theme choices are local
preferences and do not start tasks. Existing /home and /google_home routes
remain separate legacy integrations.

## Local verification

Use the loopback [fixture server](operator-panel.md#verification-without-the-robot)
and isolated tests. It imports no robot API, BUS, SDK or systemd.
Starting the production API is not a substitute for fixture verification.

[Control details](control.md) ·
[Navigation projection](../NAVIGATION_VISUALIZATION.md) ·
[Existing diagnostics and version footer](panel-diagnostics.md)
