# Navigation pulse limits

`max_motion_ms` accepts 50–500 ms, including with obstacle avoidance enabled.
The default remains 150 ms. Manual command magnitude and navigation forward/yaw
magnitude share an absolute ceiling of 1; a single manual pulse is at most 500 ms.
Saved operator settings are not increased automatically.

Pi publishes the supported ceilings in navigation configuration as
`motion_limits: {version: 1, max_speed: 1, max_motion_ms: 500,
max_turn_speed: 1, max_turn_ms: 500, max_decision_ms: 500}`.
These capability fields are not persisted policy values. Manual direction and
ramp settings remain separate from navigation's configured speed and pulse.

The setting is a ceiling, not a promise of continuous physical movement.
Each command remains bounded by the remaining capture budget, the reply validity
(up to 500 ms), the executor deadline and STOP. A configured ceiling of 500 ms
therefore does not extend a shorter decision. Normalized SDK command magnitude
is not a calibrated physical velocity.

Older devices retain their original limits. The panel must use the reported
capability and must not advertise 500 ms merely because its UI was updated.
Saving motion-policy changes revokes the existing driving acceptance. Testing
physical travel still requires the operator's separate motion authorization.
