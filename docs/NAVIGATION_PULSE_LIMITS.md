# Navigation pulse limits

`max_motion_ms` accepts 50–250 ms, including with obstacle avoidance enabled.
The default remains 150 ms. The device publishes its supported ceiling through
`motion_limits: {version: 1, max_motion_ms: 250}` in the navigation configuration
presentation. These capability fields are not persisted policy values.

The setting is a ceiling, not a promise of continuous physical movement.
Each command remains bounded by the remaining capture budget, the reply validity
(up to 200 ms), the executor deadline and STOP. A configured ceiling of 250 ms
therefore does not extend a 200 ms decision. Motor command magnitude is unchanged.

Older devices retain their original limits. The panel must use the reported
capability and must not advertise 250 ms merely because its UI was updated.
Saving motion-policy changes revokes the existing driving acceptance. Testing
physical travel still requires the operator's separate motion authorization.
