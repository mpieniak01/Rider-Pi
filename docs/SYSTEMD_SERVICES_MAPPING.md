# Task and unit mapping

Contract version 2 is defined in `common/service_catalog.py`. Installation and readiness come from API observations, not repository file presence.

[Contract and migration](TASKS_SERVICES_RESOURCES.md).

| Task | Name | Default members | Can move |
| --- | --- | --- | --- |
| S0 | `s0_core` | `rider-broker.service`, `rider-api.service`, `motion-executor.service`, `sensor-reader.service`, `rider-web-bridge.service`, `rider-core.target` | false |
| S1 | `s1_manual` | `rider-broker.service`, `rider-api.service`, `motion-executor.service`, `sensor-reader.service`, `rider-web-bridge.service`, `rider-core.target` | true |
| S2 | `s2_camera_preview` | `rider-broker.service`, `rider-api.service`, `motion-executor.service`, `sensor-reader.service`, `rider-web-bridge.service`, `camera-capture@raw.service`, `frame-distributor.service`, `rider-core.target` | false |
| S3 | `s3_follow_me_face` | `rider-broker.service`, `rider-api.service`, `motion-executor.service`, `sensor-reader.service`, `rider-web-bridge.service`, `camera-capture@raw.service`, `frame-distributor.service`, `rider-tracker.service`, `rider-tracking-controller.service`, `rider-followme.target` | true |
| S3 | `s3_follow_me_hand` | `rider-broker.service`, `rider-api.service`, `motion-executor.service`, `sensor-reader.service`, `rider-web-bridge.service`, `camera-capture@raw.service`, `frame-distributor.service`, `rider-tracker.service`, `rider-tracking-controller.service`, `rider-followme.target` | true |
| S4 | `s4_recon` | `rider-broker.service`, `rider-api.service`, `motion-executor.service`, `sensor-reader.service`, `rider-web-bridge.service`, `camera-capture@raw.service`, `frame-distributor.service`, `rider-vision.service`, `rider-obstacle.service`, `rider-odometry.service`, `rider-mapper.service`, `rider-navigator.service`, `rider-recon.target` | true |
| S5 | `s5_voice` | `rider-broker.service`, `rider-api.service`, `motion-executor.service`, `sensor-reader.service`, `rider-web-bridge.service`, `rider-voice-web.service`, `rider-voice.service`, `rider-voice.target` | false |
| S6 | `s6_tracker_module` | `rider-broker.service`, `rider-api.service`, `motion-executor.service`, `sensor-reader.service`, `rider-web-bridge.service`, `camera-capture@raw.service`, `frame-distributor.service`, `rider-tracker.service`, `rider-tracker.target` | false |
| S7 | `s7_obstacle_module` | `rider-broker.service`, `rider-api.service`, `motion-executor.service`, `sensor-reader.service`, `rider-web-bridge.service`, `camera-capture@raw.service`, `frame-distributor.service`, `rider-vision.service`, `rider-obstacle.service`, `rider-obstacle.target` | false |
| S8 | `s8_mapping` | `rider-broker.service`, `rider-api.service`, `motion-executor.service`, `sensor-reader.service`, `rider-web-bridge.service`, `camera-capture@raw.service`, `frame-distributor.service`, `rider-vision.service`, `rider-obstacle.service`, `rider-odometry.service`, `rider-mapper.service`, `rider-mapbuild.target` | false |
| S9 | `s9_navigation` | `rider-broker.service`, `rider-api.service`, `motion-executor.service`, `sensor-reader.service`, `rider-web-bridge.service`, `camera-capture@raw.service`, `frame-distributor.service`, `rider-vision.service`, `rider-obstacle.service`, `rider-odometry.service`, `rider-mapper.service`, `rider-navigator.service`, `rider-navigate.target` | true |
| S10 | `s10_ai_providers` | `rider-broker.service`, `rider-api.service`, `motion-executor.service`, `sensor-reader.service`, `rider-web-bridge.service`, `rider-ai-provider.target` | false |
| S11 | `s11_dev_mode` | `rider-broker.service`, `rider-api.service`, `motion-executor.service`, `sensor-reader.service`, `rider-web-bridge.service`, `camera-capture@edge.service`, `rider-dev.target` | false |

Optional targets are markers. Task API manages explicit members and shared consumers. Readiness includes the motion gate and producer acceptance. S6 is passive; S7 uses local OR PC vision; S11 selects one tool and never starts Jupyter. ASR/TTS use one selected-domain worker; full voice also starts the listener CLI.
