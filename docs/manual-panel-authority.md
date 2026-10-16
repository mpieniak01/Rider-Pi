# Manual panel ownership

The safety snapshot advertises optional panel ownership through
`panel_control: {"version": 1, "holder": null}`. Version 1 binds operator manual
ARM to one ephemeral browser `panel_id`. Send that same identity with each
manual actuator command, including hold and release. Existing generation,
sequence, timestamp, TTL and settings revision checks still apply.

`panel_id` is a nonblank string of at most 128 characters. It is an intent
identity, not a credential. Keep it in browser memory, never restore it after
reload and never treat it as a physical-motion confirmation.

A different or legacy panel cannot renew, replace or release another holder's
motion. Such a rejection reports `panel_owner_mismatch` without braking the
valid holder. To take control explicitly, DISARM/STOP first, read the new
generation, then ARM with the new identity. The old generation cannot resume.
Global STOP and DISARM remain available without a motion envelope or identity.

Legacy commands without an identity retain their previous behavior when ARM
has no bound holder. A newer client must not offer click-to-continue driving
on Pi versions which do not advertise this capability. Explicit takeover from
a legacy panel uses the same stop, generation refresh and ARM sequence.

This addition changes neither the manual settings nor the watchdog: the panel
reads renewal and timeout values from Pi and sends serial hold commands.
Missing renewals stop the target and output through the existing controller.
Left/right retain their existing meaning: turn in place, not curved driving.

Software acceptance uses `tests/test_panel_authority.py` and the existing motion
suites with in-memory adapters. Physical acceptance is a separate operator step.
Do not infer physical motion from an accepted command or a nonzero SDK output.
