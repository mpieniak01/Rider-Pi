# Command magnitude curves

Control and Calibration offer Linear / Smooth S / Logarithmic.
`values.ramp_mode` (0/1/2) is stored on Pi and in named profiles.
Options and labels come from `parameter_schema.ramp_modes`.
Older settings/profiles without the field use 0, preserving behavior.
Changing the selector remains a draft until Save settings on robot.

Linear has constant slope. Smooth S uses 6x^5−15x^4+10x^3 for gentle endpoints.
Logarithmic uses log(1+4x)/log(5), with its highest slope at the start.
Each curve extends transition time by its maximum slope factor to preserve
the configured %/s limit. For 0 → 60% at 50%/s: linear 1200 ms, S 2250 ms,
logarithmic approximately 2982 ms. Target, minimum, maximum and slider step
are not rescaled.

Renewing an unchanged hold preserves curve progress. A new goal replans from
current output and can change slope; this is command smoothing, not a complete
physical jerk/acceleration controller. Reversal passes through zero. A pulse
reserves ramp-down time and never extends TTL. STOP and watchdog bypass curves
and zero output immediately. Displayed pulse ≤ is a shared upper bound derived
from rates, not a promise that every curve reaches it. A short S pulse may be
too small to move the robot physically.

Implementation: [dynamics](../apps/motion/dynamics.py),
[settings](../apps/motion/manual_settings.py);
software checks: [curve tests](../tests/test_motion_curves.py).
A code deployment affecting the executor/API needs scoped service handling;
merely editing this guide does not. Sniffer recording remains optional and
does not automatically resume after restart. Physical response needs separate
operator acceptance. [Calibration](apps/calibration.md).
