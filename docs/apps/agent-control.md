# Commands from Venom conversations

Conversation support is enabled on Venom. Pi retains calibration, the motion
executor and operator ARM. The agent cannot arm, clear E-Stop, start a hold,
or change height, balance or manufacturer actions.

## One calibrated pulse

`GET /api/control/agent/state` returns `rider.safety` v1, including
`safety.agent_epoch`, `agent_last_seq`, active source and remaining manual
priority time.

`POST /api/control/agent/pulse` requires the private Bearer
`RIDER_AGENT_TOKEN`. Its body contains exactly generation, agent_epoch, seq,
ts, ttl_ms, settings_revision, request_id, intent_id, channel and direction.
Channel is chat or voice; direction is forward, backward, left or right.

Pi creates source=agent, execution_context=agent and one device_settings pulse.
Magnitude and duration come from current Pi calibration, with a maximum of
1 s. The agent cannot supply vx, yaw or a duration. The same token signs
canonical JSON with HMAC on the local BUS. The executor verifies the signature;
neither token nor signature appears in public state or ACK.

Movement requires existing operator ARM (panel/manual/operator); a test session
does not authorize an agent. Every accepted manual command changes agent_epoch.
Active manual control and a further 0.5 s priority period block agent commands.
The agent has its own sequence. A stale rejection neither brakes newer manual
control nor disarms. The host retains the original intent epoch and never
refreshes it after cancellation or retries a POST with an unknown outcome.

Public `/api/control` rejects agent commands. STOP remains available through
`POST /api/stop` with the actual source=agent and execution_context=agent.
Cancelling an old conversation does not automatically send a global STOP.
SDK ACK does not establish physical completion.

## Prepared speech playback

`POST /api/voice/playback` accepts binary audio/wav, the same private Bearer,
`X-Rider-Playback-Id` (1–64 identifier characters) and
`X-Rider-Playback-TTL-Ms` (1–60000 ms remaining budget).
Limits: 2 MiB, mono PCM16, 8–48 kHz, at most 15 s. It does not start local TTS.

The envelope is `rider.audio` v1. HTTP 200/state=played confirms the playback
program completed, not that the operator heard sound. One player and one lock
are shared by API, CLI and voice, without a queue. Repeating a successful ID
returns the saved result without playing it again.

During playback, voice closes the microphone and discards the whole utterance,
including buffered input from before playback detection. Player state and
generation share the same lock, detecting even short playback between microphone
frames. After playback it waits another 350 ms before opening a new read.
The robot's own speech must not return as a conversation command.

`POST /api/voice/playback/cancel` takes `{playback_id}` and the Bearer.
Cancellation before upload completion blocks a late start. Cancel/OFF stops
the player and closes handles without changing ARM. Busy returns 429,
unavailable player 503, cancellation or expiry 409.

## Pi voice and configuration

`text.respond` remains text task R2. Voice selects optional
`conversation.respond` only when listed in selected.tasks and its current
capability reports available=true. Only client=voice may request that task.
STT/TTS remain shared. Host data.speech_played=true prevents duplicate local
synthesis and playback.

Keep RIDER_AGENT_TOKEN only in private Pi/module environment. API and the motion
executor optionally load /etc/default/rider-compute. Never publish tokens in
the repository, URLs, BUS or logs.

`tests/test_agent_motion_contract.py`, `tests/test_audio_playback_api.py`
and compute/voice tests use mocks. Hardware and physical movement have separate
operator acceptance. See [manual control](../api-specs/manual-motion.md).
