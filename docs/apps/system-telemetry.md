# CPU/RAM history and diagnostics

`GET /sysinfo` (`rider.system`, version 1) preserves existing fields and adds continuity metadata. Linux supplies CPU/RAM; wired power, learning/lying mode and DISARMED do not imply a host restart.

## Sampling and validity

The shared sampler remains demand-driven and sleeps after 30 s without reads. CPU reads run every 250 ms, summaries every 1 s and slow disk reads every 60 s. These values are unchanged. Additional panels do not create more producers.

History retains up to 60 real rows in process memory. It is not session recording and never backfills missing observations. CPU and RAM validity are independent: unknown CPU is null while valid RAM still enters history. A failed memory read does not produce a false 0%.

An exception no longer permanently terminates the sampler. Recovery is bounded by the summary cadence and still honors idle. The last valid snapshot retains its source time; `stale=true` indicates a producer error. A failed cold start yields null values.

## Additional fields

| Field | Meaning |
| --- | --- |
| `observation.boot_id` | Linux boot identity; null if unavailable. |
| `observation.instance_id` | Sampler identity within the API process; changes with a new instance. |
| `observation.generation` | Subsequent sampler start after a pause. |
| `observation.sequence` | Real row sequence within the instance. |
| `observation.state` | `warming`, `collecting`, `error`; internally also `idle` before a new read. |
| `observation.age_s`, `monotonic_s` | Monotonic age and time of the last successful observation. |
| `observation.error_count`, `last_error_at`, `last_error_code` | Count, time and exception class name, without raw error contents. |
| `hist_mono`, `hist_generation`, `hist_seq` | Arrays aligned with the existing history arrays. |

`hist_ts` and `ts` remain wall time. New observations use monotonic ordering and placement, so wall-clock corrections cannot reverse the trace. `cpu_peak_pct` means the aggregate CPU maximum across subintervals, not a single core.

## Presentation and failures

Both panels show the last 60 s, age retained history and break curves on gaps, missing channels, generation changes or sequence discontinuities. Legacy data without metadata uses timestamps and gap detection. Compatibility does not provide full restart diagnostics for older API versions.

The panel retains history after HTTP failure. The Venom module does not refresh cached observation ages or transfer history across devices or module sessions. Confirmed boot, API instance or sampler generation changes produce distinct event labels; a gap alone does not diagnose a reboot.

A failed Venom tunnel does not prove that the direct LAN panel failed. Transport interruptions and forward conflicts require correlated evidence; an unconfirmed cause remains unknown. This change does not modify SSH, frequencies, timeouts, safety thresholds or actuators.
