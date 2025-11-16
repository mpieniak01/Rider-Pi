# Provider / PC Offload Integration

Single source of truth for the contract between the Rider-Pi device and the Rider-PC companion stack.  
This document complements the external design notes that live in the Rider-PC repository (see
[`Rider-Pc/docs/RIDER_PI_ARCH.md`](https://github.com/mpieniak01/Rider-Pc/blob/main/docs/RIDER_PI_ARCH.md) and
[`Rider-Pc/docs/ARCHITECTURE.md`](https://github.com/mpieniak01/Rider-Pc/blob/main/docs/ARCHITECTURE.md)).

## 1. Goals

1. Allow operators to switch AI workloads (Vision / Voice / Text) between on-device processing and PC providers without service restarts.
2. Keep Rider-Pi lightweight – in `pc` mode it should only capture sensor data, forward frames/chunks to Rider-PC and replay the enriched results.
3. Maintain backward compatibility for existing REST APIs and ZMQ topics. New provider capabilities must be additive.
4. Provide a deterministic handshake, health model, and rollback/fallback rules when Rider-PC becomes unavailable.

## 2. Components & Responsibilities

| Component | Location | Responsibilities |
| --- | --- | --- |
| **Provider Registry** (`services/provider_registry.py`) | Rider-Pi | Stores current provider choice per domain, exposes REST API (`/api/providers/*`), publishes bus events (`provider.*.state`), runs heartbeat monitors and triggers failback on repeated errors. |
| **Domain adapters** (`apps/vision`, `apps/voice`, `apps/chat`) | Rider-Pi | Read provider selection, either execute local pipelines or stream raw data to Rider-PC. They publish/subscribe to the same topics as today, so the rest of the system (navigator, UI) does not change. |
| **Rider-PC provider stack** (`Rider-Pc/pc_client`) | PC | Consumes REST/ZMQ data, runs heavy ML models (Whisper, YOLOv8, Ollama, etc.), publishes enhanced results back to Rider-Pi via ZMQ, exposes `/providers/*` endpoints for status and capability negotiation. |
| **Control UI** (`web/control.html`) | Rider-Pi | Presents the Provider Control panel with toggles per domain, shows connection state and last change timestamps, and calls `/api/providers/*` endpoints. |

## 3. REST API Contract (Rider-Pi)

| Endpoint | Method | Payload / Response | Notes |
| --- | --- | --- | --- |
| `/api/providers/state` | `GET` | ```json\n{\n  \"domains\": {\n    \"vision\": {\"mode\": \"local\", \"status\": \"online\", \"changed_ts\": 1713360000.0},\n    \"voice\":  {...},\n    \"text\":   {...}\n  },\n  \"pc_health\": {\"reachable\": true, \"latency_ms\": 32}\n}\n``` | Used by the UI to render switches and indicators. |
| `/api/providers/{domain}` | `PATCH` | `{"target": "local"|"pc", "force": false}` | Domain ∈ {`vision`, `voice`, `text`}. When switching to `pc` the registry validates Rider-PC capability and publishes `provider.{domain}.state`. |
| `/api/providers/health` | `GET` | Aggregated heartbeat table with RTT, last success, error counters. | Feed for monitoring dashboards and CLI diagnostics. |
| `/api/system/ai-mode` | `PUT/GET` | Existing AI mode endpoint. | Remains the low-level switch used by legacy services; registry drives this automatically per domain. |

### Capability Negotiation (Pi → PC)

1. Registry calls `GET http://pc-host:8000/providers/capabilities`.
2. Rider-PC responds with supported domains and schema versions:
   ```json
   {
     "vision": {"version": "1.1.0", "features": ["obstacle", "depth"]},
     "voice":  {"version": "1.0.0", "features": ["asr", "tts"]},
     "text":   {"version": "1.0.0", "features": ["llm"]}
   }
   ```
3. If Rider-Pi requires a newer schema, the registry keeps domain in `local` and marks status as `blocked`.

## 4. ZMQ Topics

| Direction | Topic | Payload | Description |
| --- | --- | --- | --- |
| Pi → PC | `vision.frame.offload` | `{ "rid": "camera0", "ts": 123.4, "frame_jpeg": "<base64>", "roi": {...} }` | Raw frames (or ROI crops) streamed when `vision` domain is set to `pc`. |
| Pi → PC | `voice.asr.request` | `{ "rid": "voice", "ts": 123.4, "chunk_pcm": "<base64>", "lang": "pl-PL" }` | Audio chunks captured locally. PC replies on `voice.asr.result`. |
| Pi → PC | `voice.tts.request` | `{ "text": "...", "voice": "piper-pl" }` | Optional – rider voice lines synthesized on PC. |
| PC → Pi | `vision.obstacle.enhanced` | `{ "present": true, "distance": 0.7, "angle": -12.0, "confidence": 0.91, "ts": 123.5 }` | Consumed by navigator instead of local ROI detector. |
| PC → Pi | `voice.asr.result` | `{ "text": "...", "intent": {...}, "reply": "...", "tts": {...}, "ts": 123.5 }` | Provides transcript plus optional intent/command, reply text, and inline TTS audio (base64). |
| PC → Pi | `voice.tts.chunk` | Streaming PCM chunks rendered on Rider-PC (optional alternative to inline `tts`). |
| PC → Pi | `provider.{domain}.heartbeat` | Short health pings consumed by the registry (alternative to HTTP heartbeat). |

All topics continue to use the existing broker (`services/broker.py`, ports 5555/5556). Messages must remain backward compatible for subscribers (UTF-8 JSON).

## 5. Data Flows

### Mode Switch
1. Operator toggles domain in Provider Control card (`web/control.html`).
2. UI calls `PATCH /api/providers/{domain}`.
3. Registry validates Rider-PC capability + heartbeat.
4. Registry updates local state, persists it, emits `provider.{domain}.state` event and optionally adjusts `RIDER_AI_MODE`.
5. Domain adapter receives the event and either resumes local processing or starts streaming to Rider-PC.

### Vision Offload
1. `apps/vision` uses `VisionDispatcher` to capture frames and push them to `vision.frame.offload`.
2. Rider-PC receives frames, runs YOLO/depth models, publishes `vision.obstacle.enhanced`.
3. Navigator subscribes to the enhanced topic (already implemented) and fuses the data for motion planning.
4. Rider-Pi republishes `vision.obstacle.enhanced` as simplified payloads on `vision.obstacle` so legacy listeners keep working. Rider-PC only needs to send the enhanced topic.

### Voice Offload
1. `apps/voice` captures PCM, wraps it in `voice.asr.request`, and waits for `voice.asr.result`.
2. When text is produced, the existing pipelines (NLU, chat, control intents) continue unchanged. If Rider-PC provides an `intent` object, Rider-Pi reuses it instead of running its own NLU.
3. For TTS, Rider-PC can send inline audio in the `tts` field or publish `voice.tts.chunk`; Pi plays it directly and skips local synthesis.
4. Rider-Pi expects periodic `voice.asr.result` payloads even when no user speech is present (e.g., `{"text": "", "status": "idle"}` every few seconds). Lack of responses triggers automatic fallback to local processing.

### Text / LLM Offload
1. Chat service consults the registry. In `pc` mode it calls `http://pc-host:8000/providers/text/generate`.
2. Responses are passed to the face renderer / voice stack exactly as in local mode.

## 6. Failure Handling

- **Heartbeat**: Registry polls Rider-PC every `PROVIDER_HEALTH_INTERVAL` seconds. Failure threshold triggers automatic fallback to `local`.
- **Circuit breaker**: Each domain tracks consecutive errors. Example defaults: 3 failed inference requests or >2 s timeout triggers fallback.
- **Graceful degrade**: When PC becomes unavailable the registry publishes `provider.{domain}.state` with `status="fallback"` so UI can show warnings.
- **Manual override**: Operators can force `local` even if PC is healthy. Force parameter bypasses capability mismatch (use with caution).

## 7. Implementation Roadmap

1. **Phase 1 – Registry & Docs**
   - Implement `provider_registry.py`, REST endpoints, persistence (`data/providers_state.json`).
   - Update UI with Provider Control card (read-only until PC stack is ready).
2. **Phase 2 – Vision Offload MVP**
   - Build `VisionDispatcher`, publish frames, consume enhanced data from Rider-PC mock.
   - Navigator + mapper validated end-to-end.
3. **Phase 3 – Voice/Text Integration**
   - Stream audio chunks, integrate Rider-PC Whisper/Piper pipelines, add `/providers/text/*`.
4. **Phase 4 – Monitoring & Ops**
   - Metrics (`/api/app-metrics` group `provider`), Grafana dashboards, systemd units for provider bridge.

## 8. Testing Checklist

- Contract tests verifying JSON schema compatibility with Rider-PC (pytests with fake ZMQ endpoints).
- UI Cypress test ensuring toggles call the registry and respond to fallback events.
- Integration test for navigator verifying automatic switch to `vision.obstacle.enhanced`.
- Load tests for frame streaming (capture at 5 FPS, 640×480) to validate CPU and bandwidth.
- Failure injection tests: drop Rider-PC connection and confirm fallback to local within ≤2 seconds.

## 9. Related Documents

- [`docs/ui/control.md`](ui/control.md) – describes the Provider Control card in the web UI.
- [`docs/AI_MODE_SWITCHER.md`](AI_MODE_SWITCHER.md) – explains the legacy AI mode switcher. The provider registry builds on top of it for per-domain routing.
- [`docs/_todo/rider_pi_device_architecture.md`](./_todo/rider_pi_device_architecture.md) – legacy draft; this document supersedes it.
