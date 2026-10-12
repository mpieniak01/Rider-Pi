# System measurements and panel refresh

The API has one demand-driven sampler per process. CPU counters are read every
250 ms; a weighted CPU average, short-sample maximum, RAM, load and temperature
are published together every second. HTTP reads only return snapshots.
Disk and OS information are refreshed every 60 seconds. The sampler sleeps after
30 seconds without a metrics reader and starts again on demand, leaving real
timestamp gaps rather than inventing missing history.

Existing CPU/RAM arrays remain compatible. Additive fields in /sysinfo:
cpu_peak_pct, hist_cpu_peak, hist_ts and sampling. Current values and the last
history point refer to the same sample. The chart displays the last 60 seconds
with separate average/peak CPU lines; its peaks cover 250 ms measurement windows,
not instantaneous CPU spikes.

The panel uses shared profiles: telemetry 1 s, system 2 s, services 5 s,
inventory 10 s, vision 2 s and application metrics 10 s. /sysinfo publishes
presentation timing hints. Stable profile beats share requests among widgets,
with different phases for expensive groups. Successful catalog reads may be
shared for one second within a tab. Explicit camera actions and contract
negotiation bypass that cache; mutations invalidate it, including in-flight
results from the preceding generation. Hidden tabs sleep and failures back off.

Motion, safety-state polling, hold renewal and calibration synchronization retain
their existing timing. Presentation hints never set actuator timing or watchdog
limits. Rider-PC and other clients remain compatible with existing fields.
Multiple API processes each have their own sampler/cache.


Stable free resources and failed owner probes now share their observations for
5 seconds (busy resources: 3 seconds). Resource recovery remains a fresh direct
inspection; its result invalidates the presentation cache.


The API configures the existing common systemd observer for a 2-second cache,
without adding another service-state cache. Actions retain explicit invalidation.
Overview requests historical frame metadata once while idle; it does not poll
the absent obstacle producer and resumes vision reads after observed camera ON.
