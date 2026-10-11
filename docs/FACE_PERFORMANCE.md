# Rider-Pi face measurements

Measured on the original XGO-Rider CM4 (Python 3.9, Pillow 9.5.0), 2026-10-12.
Baseline: `354cfddccb7602de4e642d0f454af8f6821364ef`. Implementation verified
on local preview `5756357fd3c0670f4d414a20900e40afdaef2da6`.

## Rendering benchmark

`scripts/face_benchmark.py` renders 240×240 dynamic frames and converts each
to RGB565. Each variant uses a separate process, 20 warm-up frames, 300 timed
frames, followed by a three-second run paced at 12 FPS. CPU is process CPU
time divided by wall time; 100% means one CPU core.

| Variant | Mean | p95 | CPU at 12 FPS | Peak process RSS | Loop RSS growth |
| --- | ---: | ---: | ---: | ---: | ---: |
| Friendly | 4.727 ms | 5.360 ms | 6.01% | 34.99 MiB | 2.11 MiB |
| Simple | 4.763 ms | 5.470 ms | 5.70% | 35.27 MiB | 2.07 MiB |
| Previous renderer | 12.037 ms | 12.647 ms | 14.74% | 35.36 MiB | 1.41 MiB |

The new component meets the initial ≤5 ms mean / ≤10 ms p95 rendering goals.
It encoded **zero PNGs** in the benchmark. Peak RSS remained comparable to
the previous component. This short run does not establish long-term memory
stability; fixed-size caches and channel limits also have targeted tests.

These are **rendering component measurements**, excluding SPI, API requests,
browser preview and other robot services. They do not establish total API
CPU, battery consumption or operating time.

Reproduce on Pi without opening LCD or UART:

```sh
python3 scripts/face_benchmark.py --style friendly
python3 scripts/face_benchmark.py --style minimal
python3 scripts/face_benchmark.py --baseline-ref 354cfddccb7602de4e642d0f454af8f6821364ef
```

## Device and browser observations

- Operator confirmed that the happy face was visible and correct on the LCD.
  The existing 270° orientation was retained.
- With natural idle disabled, the frame counter stayed at four across
  repeated observations: an unchanged face was not continuously sent to SPI.
- A battery-mode trial stopped after approximately 45 seconds and reported
  accepted backlight-off control. A later cable-mode trial was explicitly
  stopped at the operator's request; the worker stopped and reported LCD off.
  Settings were then returned to battery mode, with natural idle enabled.
- The last changed-frame LCD presentation in the cable trial took 67.56 ms.
  This is one observation, **not** mean/p95 SPI latency. It also includes
  canvas composition and device reporting.
- The CM4's Pillow 9.5 rounded-rectangle edge case and the vendor driver's
  shared SPI handle were addressed. The repeated-session recovery has a
  targeted ownership/reopen test; another physical stop/start cycle after
  that fix was not run after the operator requested LCD off.
- The actual Pi Studio URL, desktop/mobile layout, shared settings,
  draft frames, live-worker frames and inactive-frame handling were checked
  in a browser. The live source mirrors the active face worker only.
- Preview rollback to the clean baseline and redeployment were exercised.
  The motion executor was neither restarted nor sent movement commands.

## Software verification

Final local regression: **1817 Python tests passed**, 40 skipped,
8 subtests passed; **141 JavaScript tests passed**; Ruff and diff checks passed.
Hardware-free targeted coverage includes animation replacement/priority,
audio watchdog, direct frame caching, catalog limits, atomic persistence,
settings conflicts, LCD ownership, orientation and closure, and hidden-tab
request/timer cleanup.

Physical camera/voice concurrency, long-duration CPU/RAM, representative SPI
latency and energy measurements remain future hardware checks. No claim of
measured battery savings or integration with an external speech provider is made.
