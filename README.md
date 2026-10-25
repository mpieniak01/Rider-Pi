<p align="center">
  <img src="./data/splash_logo.png" width="200" alt="Rider-Pi logo">
</p>

# Rider-Pi 1.0.0

[![Release](https://img.shields.io/badge/release-v1.0.0-blue)](https://github.com/mpieniak01/Rider-Pi/releases/tag/v1.0.0)
[![Tests — main](https://github.com/mpieniak01/Rider-Pi/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/mpieniak01/Rider-Pi/actions/workflows/tests.yml?query=branch%3Amain)
[![Quality Guard — PR](https://github.com/mpieniak01/Rider-Pi/actions/workflows/quality-guard.yml/badge.svg?event=pull_request)](https://github.com/mpieniak01/Rider-Pi/actions/workflows/quality-guard.yml)
[![SonarCloud Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=mpieniak01_Rider-Pi&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=mpieniak01_Rider-Pi&branch=main)
[![Coverage — main](https://sonarcloud.io/api/project_badges/measure?project=mpieniak01_Rider-Pi&metric=coverage)](https://sonarcloud.io/component_measures?id=mpieniak01_Rider-Pi&branch=main&metric=coverage&view=list)
[![Snyk monitoring](https://snyk.io/test/github/mpieniak01/Rider-Pi/badge.svg)](https://snyk.io/test/github/mpieniak01/Rider-Pi)
[![GitGuardian — PR secret scanning](https://img.shields.io/badge/GitGuardian-PR%20secret%20scanning-blue)](https://github.com/mpieniak01/Rider-Pi/pulls)

[Dokumentacja po polsku](README_PL.md) · [Documentation](docs/README.md) · [Release notes](docs/release-notes/v1.0.0.md)

Independent, educational software for the two-wheeled Yahboom Rider-Pi robot.
It runs local applications, exposes an operator panel and keeps hardware execution
on the Raspberry Pi. This is a community project, unaffiliated with the manufacturer.

<p align="center">
  <a href="./data/Rider-Pi_01_a64b25c8-2cba-4f4e-b1d8-8cd5d543a9fb_600x.webp">
    <img src="./data/Rider-Pi_01_a64b25c8-2cba-4f4e-b1d8-8cd5d543a9fb_600x.webp" width="420" alt="Two-wheeled Rider-Pi robot">
  </a>
</p>

## Quality signals

| Signal | What it reports |
| --- | --- |
| Tests | Latest `main` run of the Python 3.9 software and API regressions, including isolated JavaScript fixtures. |
| Quality Guard | Latest PR workflow: Ruff 0.6.9, changed Python file limits, static systemd validation and API checks. |
| SonarCloud | Live `main` quality gate; CI imports Python and JavaScript coverage for the analyzed revision. |
| Coverage | Overall coverage of `main`; the gate separately requires at least 80% coverage of new code. |
| Snyk | External dependency monitoring. Its badge can say **monitored**; inspect the PR check for its verdict. |
| GitGuardian | Informational badge identifying PR secret scanning; the actual result is in each PR's checks. |

Workflow badges show their latest scoped run. Before merging, check results for
the current PR head; after merging, check the new `main` SHA. Software checks do
not establish physical robot safety. [Quality gate and reproduction](docs/QUALITY_GATE.md).

## Capabilities and boundaries

- **Operator panel and API:** manual controls, service/resource diagnostics, camera
  preview, calibration profiles and a Git revision footer. HTTP API uses port 8080;
  the optional motion bridge uses 8081.
- **Motion authority:** one executor owns the UART. Commands carry identity,
  generation, sequence and expiry; acknowledgments distinguish accepted commands
  from physical completion. ARM and clearing E-Stop require operator consent.
- **LCD:** animated face, device status and boot splash with exclusive ownership,
  guarded power control and idle sleep. Preserve the installed 270° compensation.
- **Camera, voice and chat:** optional profiles activated on demand, with explicit
  backend requirements. Google OAuth/SDK integrations are optional, outside the
  base software-test dependencies.
- **Venom integration:** a paired external module provides optional compute and
  bounded navigation decisions. Pi retains hardware authority and validates
  replies. Configuration, transport and model availability require their own setup.
- **Experimental autonomy:** Follow Me, mapping, odometry and navigation modules
  support development and controlled trials. A map or depth estimate is not a
  validated collision sensor or a guarantee of autonomous return-to-home.

Read [motion and safety](docs/apps/safety.md), the
[directional navigation contract](docs/DIRECTIONAL_NAVIGATION.md) and
[Venom compute](docs/COMPUTE_VENOM.md) before selecting those profiles.

## Runtime and setup

The supported device baseline is the manufacturer's Raspberry Pi OS / Debian 11
Bullseye image with **Python 3.9**. A newer WSL Python does not qualify a device
runtime upgrade. Version 1.0.0 identifies this project, separately from vendor SDK,
firmware and HTTP contract versions; [VERSION](VERSION) is the release metadata.

Use [deployment and recovery](docs/DEPLOYMENT.md) for an existing robot and the
[environment policy](docs/ENVIRONMENT_POLICY.md) to prepare development. Keep Pi,
Rider-PC and Venom dependencies in their own environments. Install only the
packages needed by the selected Pi profile; keep dev/test dependencies in WSL/CI.
Preserve existing local configuration and secrets.

On an already configured Pi, these requests only observe state:

```sh
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/api/safety
curl --fail http://127.0.0.1:8080/api/status/version
```

Open `http://<robot-ip>:8080/` for the overview and `/control` for the operator
panel. Loading a page or deploying code does not authorize ARM or movement.
Physical movement needs a separate operator-approved plan and prepared space.

## Development

From the Rider-Pi checkout, use its existing virtualenv:

```sh
.venv/bin/python --version
make test-env
make lint
make test TEST_ARGS='-q tests/test_version_api.py tests/test_boot_lcd_handover.py'
```

These are focused software checks. CI also executes Python 3.9 and the full
isolated Python/JavaScript coverage suites through the Sonar workflow. Hardware,
physical-motion and network tests are excluded from that automatic suite.
See [development](docs/development.md) and [contributor instructions](AGENT.md).

Application delivery uses a local commit and scoped Pi preview, then PR, checks,
review, merge and release of the exact `main` SHA. Restart only the affected
service when needed. Documentation-only changes require no hardware restart.
[Version and tag procedure](docs/VERSIONING.md).

## Project map

| Directory | Responsibility |
| --- | --- |
| `apps/` | Robot applications, safety executor, LCD, camera, voice and navigation. |
| `services/` | HTTP API, orchestration and service/resource projections. |
| `common/`, `drivers/` | Shared contracts and validated hardware access. |
| `web/` | Operator panel and web assets. |
| `config/`, `systemd/`, `scripts/` | Public configuration templates, units and operational tools. |
| `tests/` | Isolated software regressions and explicitly marked hardware tests. |
| `docs_pl/`, `docs/` | Polish and English maintained documentation. |

## Documentation

- [Project vision](PROJECT.md), [architecture](ARCHITECTURE.md) and [documentation index](docs/README.md).
- [API contracts](docs/api-specs/README.md), [operator panel](docs/ui/operator-panel.md) and [calibration](docs/apps/calibration.md).
- [LCD ownership and startup](docs/apps/face-lcd.md), [camera](docs/apps/camera.md) and [voice](docs/apps/voice.md).
- [Systemd service mapping](docs/SYSTEMD_SERVICES_MAPPING.md) and [configuration policy](docs/config/POLICY.md).
- [Release 1.0.0](docs/release-notes/v1.0.0.md), [versioning](docs/VERSIONING.md) and [documentation policy](docs/DOCUMENTATION_POLICY.md).


Current guides: [manual pulse/hold/release](docs/api-specs/manual-motion.md),
[panel ownership](docs/manual-panel-authority.md),
[revision 2 policy parameters](docs/vision-policy-parameters.md) and
[visual image reference](docs/IMAGE_REFERENCE.md).

## License and contributions

Contributions and feedback are welcome. The project uses the [MIT License](LICENSE).
Thanks to the Yahboom/XGO platform and the open-source Python, OpenCV and ZMQ ecosystems.

Copyright (c) 2025–2026 Maciej Pieniak.
