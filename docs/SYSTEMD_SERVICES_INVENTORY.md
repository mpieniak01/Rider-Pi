# Service catalog inventory

Contract version 2 is defined in `common/service_catalog.py`. Installation and readiness come from API observations, not repository file presence.

[Contract and migration](TASKS_SERVICES_RESOURCES.md).

| Unit | Host | Lifecycle | Resources | Can move |
| --- | --- | --- | --- | --- |
| `audio-input.target` | pi | on-demand | mic | false |
| `audio-output.target` | pi | on-demand | speaker | false |
| `camera-capture@edge.service` | pi | dev | camera | false |
| `camera-capture@raw.service` | pi | on-demand | camera | false |
| `camera-capture@ssd.service` | pi | dev | camera | false |
| `frame-distributor.service` | pi | on-demand | frame_feed | false |
| `jupyter.service` | pi | manual | — | false |
| `lcd-renderer.service` | pi | startup | lcd | false |
| `motion-executor.service` | pi | startup | uart | true |
| `rider-ai-provider.target` | pi | on-demand | — | false |
| `rider-api.service` | pi | startup | — | false |
| `rider-boot-splash.service` | pi | startup | lcd | false |
| `rider-broker.service` | pi | startup | — | false |
| `rider-choreographer.service` | pi | on-demand | control | true |
| `rider-core.target` | pi | startup | — | false |
| `rider-dev.target` | pi | dev | — | false |
| `rider-followme.target` | pi | on-demand | — | true |
| `rider-google-bridge.service` | pi | on-demand | — | false |
| `rider-mapbuild.target` | pi | on-demand | — | false |
| `rider-mapper.service` | pi | on-demand | — | false |
| `rider-minimal.target` | pi | startup | — | false |
| `rider-navigate.target` | pi | on-demand | — | true |
| `rider-navigator.service` | pi | on-demand | control | true |
| `rider-obstacle.service` | pi | on-demand | — | false |
| `rider-obstacle.target` | pi | on-demand | — | false |
| `rider-odometry.service` | pi | on-demand | — | false |
| `rider-recon.target` | pi | on-demand | — | true |
| `rider-tracker.service` | pi | on-demand | — | false |
| `rider-tracker.target` | pi | on-demand | — | false |
| `rider-tracking-controller.service` | pi | on-demand | control | true |
| `rider-vision-offload.service` | pi | on-demand | camera, frame_feed | false |
| `rider-vision.service` | pi | on-demand | — | false |
| `rider-voice-web.service` | pi | on-demand | — | false |
| `rider-voice.service` | pi | on-demand | mic, speaker | false |
| `rider-voice.target` | pi | on-demand | — | false |
| `rider-web-bridge.service` | pi | startup | — | false |
| `sensor-reader.service` | pi | startup | — | false |
| `wifi-unblock.service` | pi | startup | — | false |

Startup is catalog lifecycle; enabled state is observed independently. Runtime modules belong to the selected profile. Worker audio resources are assigned by domain consumers, not by its process label. UART belongs to the executor; sensor-reader consumes BUS. Camera excludes SPI/LCD. Missing/unknown is never ready.
