# Configuration guide index

Public templates belong in config/; environment-specific settings, credentials
and operational reports remain local. [Configuration policy](POLICY.md) and
[environment policy](../ENVIRONMENT_POLICY.md) define ownership and dependencies.

| Configuration | Guide |
| --- | --- |
| Voice file/streaming backends | [Voice](voice.md) and config/voice_openai_file.toml / voice_openai_streaming.toml |
| Face rendering and appearance | [Face](face.md), config/face.toml, [Face Studio](../FACE_STUDIO.md) |
| Audio devices and mixer | [ALSA](alsa.md), [WM8960](../audio/wm8960.md) |
| Validation and supported schemas | [Validation](validation.md) |
| Shared manual settings/profiles | [Calibration](../apps/calibration.md), [parameter descriptors](../api-specs/manual-motion.md) |
| Camera source/provider/transport | [Camera pipeline](../CAMERA_PIPELINE_V1.md) |
| Compute pairing | [Venom compute](../COMPUTE_VENOM.md) |
| Model settings and versioned presets | [Perception](../apps/perception-models.md), [policy parameters](../vision-policy-parameters.md) |
| Separate image measurement overlay | [Visual reference](../IMAGE_REFERENCE.md) |

Voice configuration uses CLI, supported environment overrides, the selected
TOML (VOICE_CONFIG/--config) and defaults according to the specific field.
See the voice guide and loader; do not assume every TOML key has a corresponding
environment or CLI option. Configuration validation does not install a backend.

## Local overrides and secrets

Preserve an existing .env and private settings. Public .env.example files have
placeholders only; copying one over a live .env loses configuration.
config/local/ and private env files are ignored and never belong in PR artifacts,
logs, images or deployment bundles. Ignoring a file does not untrack an existing
Git entry; inspect the staged diff.

Keep credentials in the configured private service/developer environment or
a protected local env file, with file permissions 600 where applicable.
Do not paste values into shell commands/history, public TOML or documentation.
A reference such as env:OPENAI_API_KEY names an environment variable; it is not
a literal credential and does not provision one. Each backend has its own
requirements. A standard shell/service does not automatically load every local
env file: use the project's existing loader or service configuration.

Persisted device stores have their own schemas and revisions. Updating a
template does not migrate a running device or restore movement approval.
Use the documented API/CAS transaction rather than editing active settings
while a consumer owns them. Software verification uses isolated temporary stores.
