# Decision: bounded command curves

Status: implemented as `ramp_mode`, described in [command curves](motion-curves.md).
This page records the design rationale, not a pending deployment plan or a
snapshot of any device's settings.

A linear approach bounds command change by rate × dt but changes slope abruptly
at its endpoints. Lowering the rate alone does not smooth those transitions.
A rising logarithmic curve has its steepest initial slope; Smooth S softens
both endpoints. Interpolating either in the unchanged linear duration could
exceed the original rate ceiling, so the implementation scales duration by the
curve's maximum slope.

The implemented contract has three modes: Linear, Smooth S and Logarithmic.
There is no separate persisted smoothness-ms parameter. Pi owns the setting and
profile definitions; clients use its descriptor. An unchanged hold keeps curve
progress, new goals start at current output, reversal passes through zero, and
pulse TTL is never extended. STOP, watchdog and lost execution authority zero
the output without waiting for a curve. No force/minimum increase is implied.

Software acceptance covers rates, target bounds, hold renewal, release,
reversal, pulse expiry and profile migration in
[tests/test_motion_curves.py](../tests/test_motion_curves.py).
These checks describe software commands; physical acceleration and stopping
remain separate operator measurements.
