# Rider-Pi Apps Documentation

> Central documentation index for the **Rider-Pi Apps** project — software extending the capabilities of the Rider-Pi device.

> **Note**: Historical reports in the `docs/_pr_summaries/` directory may remain in English, as they document previous project versions.

## Main Documents (Root Directory)

The most important documents are located in the project root directory:

- [**README.md**](../README.md) — project introduction, installation, quick start
- [**PROJECT.md**](../PROJECT.md) — project vision, business goals, roadmap
- [**ARCHITECTURE.md**](../ARCHITECTURE.md) — system architecture, ports, data flows
- [**ARCHITECTURE_DIAGRAM.md**](../ARCHITECTURE_DIAGRAM.md) — architecture diagrams
- [**AGENT.md**](../AGENT.md) — code assistant contract, developer guidelines
- [**WORKING-AGREEMENTS.md**](../WORKING-AGREEMENTS.md) — team working agreements
- [**CONFIG_POLICY.md**](CONFIG_POLICY.md) — **configuration and secrets policy** (single source of truth)
- [**OFFLOAD_PROVIDER_PROTOCOL.md**](OFFLOAD_PROVIDER_PROTOCOL.md) — Pi ↔ PC provider/offload contract, endpoints, topics, roadmap

---

## Application Module Documentation (`apps/*`)

Detailed documentation for all application modules:

- [**apps/README.md**](apps/README.md) — **application modules index** (overview, dependencies, startup)
- [**apps/chat.md**](apps/chat.md) — OpenAI chat (audio.transcript → GPT → tts.speak)
- [**apps/nlu.md**](apps/nlu.md) — motion intent recognition from PL transcription
- [**apps/launcher.md**](apps/launcher.md) — startup menu with 4 buttons
- [**apps/menu.md**](apps/menu.md) — navigation menu (launcher duplicate?)
- [**apps/motion.md**](apps/motion.md) — motion bridge (motion.cmd → XGO adapter)
- [**apps/safety.md**](apps/safety.md) — emergency stop (E-STOP)
- [**apps/demos.md**](apps/demos.md) — ready motion demonstrations
- [**apps/camera.md**](apps/camera.md) — camera preview with face detection on LCD
- [**apps/vision.md**](apps/vision.md) — object detection (HOG, TFLite, ROI)
- [**apps/draw.md**](apps/draw.md) — face rendering primitives
- [**apps/hw.md**](apps/hw.md) — LCD sink (framebuffer)
- [**apps/ui.md**](apps/ui.md) — buttons, UI configuration, face controller

### Module Documentation (legacy — `docs/modules/`)

- [**modules/voice.md**](modules/voice.md) — complete voice stack (ASR, TTS, VAD, KWS, chat), file and streaming modes
- [**modules/face.md**](modules/face.md) — static face render API (HTTP endpoints, configuration)
- [**modules/face-lcd.md**](modules/face-lcd.md) — face rendering on ILI9xx LCD panel
- [**modules/face-phase5-lcd.md**](modules/face-phase5-lcd.md) — phase 5 implementation documentation (LCD RAW sink)
- [**modules/sim.md**](modules/sim.md) — Rider-Pi 2D simulator, navigation algorithm testing

---

## Operational Scripts Documentation

> **Note:** Scripts were moved from `ops/` and `tools/` to `scripts/` (see [../scripts/README.md](../scripts/README.md)).  
> Documentation in `docs/ops/` describes functionality (remains current), but paths refer to the new location.

Operational scripts for system and service management:

- [**ops/README.md**](ops/README.md) — **scripts index** (conventions, security, exit codes)
- [**ops/voice-scripts.md**](ops/voice-scripts.md) — sys_voice-*.sh (voice application startup)
- [**ops/systemd-scripts.md**](ops/systemd-scripts.md) — sys_control.sh, systemd-sync.sh (service management)
- [**ops/display-scripts.md**](ops/display-scripts.md) — sys_lcd-control.py, sys_led-control.py (display control)
- [**ops/camera-scripts.md**](ops/camera-scripts.md) — sys_camera-*.sh (camera management)
- [**ops/monitoring-scripts.md**](ops/monitoring-scripts.md) — diag_metrics.sh, diag_stream.sh (monitoring)
- [**ops/utility-scripts.md**](ops/utility-scripts.md) — tests, XGO diagnostics, demos, utilities

### Systemd Service Tests

Documentation for testing and validation of `.service` files:

- [**SYSTEMD_SERVICES_MAPPING.md**](SYSTEMD_SERVICES_MAPPING.md) — systemd services → scripts mapping, post-refactoring status
- [**SYSTEMD_SERVICES_INVENTORY.md**](SYSTEMD_SERVICES_INVENTORY.md) — complete inventory of all systemd units (ExecStart, validation status)
- [**ops/systemd-scripts.md**](ops/systemd-scripts.md) — detailed validation tools documentation

**Available Tests:**

1. **Static tests** (without systemd):
   - `scripts/diag_validate-systemd-paths.py` — ExecStart path validation
   - `scripts/diag_systemd-smoke.sh` — comprehensive bash test
   - `pytest tests/test_systemd_services.py` — pytest tests

2. **Smoke tests** (require systemd):
   - `SYSTEMD_SMOKE_TESTS=1 pytest tests/test_systemd_smoke.py` — verification with systemd

**Running Locally:**

```bash
# Quick validation (no dependencies)
bash scripts/diag_systemd-smoke.sh

# Full pytest suite
pip install pytest pytest-timeout
pytest tests/test_systemd_services.py -v

# With systemd (on robot)
SYSTEMD_SMOKE_TESTS=1 pytest tests/test_systemd_smoke.py -v
```

More information: [SYSTEMD_SERVICES_MAPPING.md](SYSTEMD_SERVICES_MAPPING.md#testing)

---

## Configuration Documentation (`config/*`)

Configuration parameters for all modules:

- [**config/README.md**](config/README.md) — **parameters index** (hierarchy, precedence, secrets policy)
- [**config/voice.md**](config/voice.md) — voice_openai_file.toml, voice_openai_streaming.toml (ASR, TTS, Chat)
- [**config/face.md**](config/face.md) — face.toml (face geometry, emotions, animations)
- [**config/alsa.md**](config/alsa.md) — asoundrc.wm8960, wm8960-apply.sh (ALSA configuration)

---

## Audio Documentation

Sound card configuration and usage:

- [**wm8960.md**](audio/wm8960.md) — WM8960 card configuration for duplex audio streaming (ALSA, troubleshooting)

---

## Implementation Reports

Summaries of completed work stages:

- [**completion-report.md**](_pr_summaries/completion-report.md) — project final report
- [**implementation-summary.md**](_pr_summaries/implementation-summary.md) — implementation summary
- [**simulator-summary.md**](_pr_summaries/simulator-summary.md) — 2D simulator implementation summary
- [**sim1-implementation-summary.md**](_pr_summaries/sim1-implementation-summary.md) — SIM-1 implementation report (environment core and map rendering)
- [**sim3-implementation.md**](_pr_summaries/sim3-implementation.md) — SIM-3 implementation report

---

## Release Notes

Project release history:

- [**v0.6.md**](release-notes/v0.6.md) — version 0.6
- [**v0.5.3.md**](release-notes/v0.5.3.md) — version 0.5.3
- [**v0.5.2.md**](release-notes/v0.5.2.md) — version 0.5.2

---

## How to Add New Documentation

When adding new documents, follow these guidelines:

### 1. Location Selection

- **Root directory** — only documents with general scope (vision, architecture, working agreements)
- **`docs/apps/`** — application module documentation (`apps/*`)
- **`docs/ops/`** — operational scripts documentation (scripts in `scripts/`)
- **`docs/config/`** — configuration parameters documentation (`config/*`)
- **`docs/api/`** — REST API endpoint documentation
- **`docs/modules/`** — legacy module documentation (voice, face, sim)
- **`docs/_pr_summaries/`** — PR summaries and implementation reports
- **`docs/_todo/`** — planned work, design drafts

### 2. File Naming

- Use lowercase with hyphens: `module-name.md`
- For indexes: `README.md`
- For specific topics: descriptive name (e.g., `voice-configuration.md`)

### 3. Structure and Content

Every document should contain:

- **Title** (H1) — clear and specific
- **Overview** — brief description of topic
- **Main sections** — logical content organization
- **Examples** — code snippets, commands, configurations
- **References** — links to related documents

### 4. Cross-references

- Use relative paths: `[text](../other-doc.md)`
- Link to relevant sections: `[text](document.md#section)`
- Keep links current when moving files

### 5. Updates

- **New features** — add documentation in the same PR
- **Breaking changes** — update all affected documents
- **Deprecations** — mark deprecated sections, add migration path

---

## Documentation Maintenance

### Regular Reviews

- Check for outdated information after major changes
- Verify all links work correctly
- Update examples to match current code

### Quality Standards

- Clear, concise language
- Proper formatting (headings, lists, code blocks)
- Consistent terminology
- No sensitive information (API keys, passwords)

---

## External Resources

- [Rider-Pi Hardware](https://category.yahboom.net/products/rider-pi-robot) — manufacturer's website
- [Raspberry Pi Documentation](https://www.raspberrypi.org/documentation/) — official RPi docs
- [ZMQ Guide](https://zguide.zeromq.org/) — ZeroMQ messaging guide
