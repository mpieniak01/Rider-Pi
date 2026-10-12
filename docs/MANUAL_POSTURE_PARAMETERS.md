# Device-owned posture parameters

GET /api/calibration/controls publishes parameter_schema.actuator_fields for height and balance. The common definition also drives HTTP, executor and SDK validation.

- Height: integer SDK command, range 75–115, step 1. This is not a measured height and is not specified in millimeters.
- Balance: boolean roll compensation (rider_balance_roll), not shutdown of the complete equilibrium controller.
- Capabilities independently describe availability; metadata never grants permission to actuate.
- Height/balance commands use the existing manual envelope, current settings_revision and the Pi safety gate. Reading metadata and saving calibration never actuates the robot.

The authoritative definitions are in common/actuator_parameters.py. Automatic checks use fake adapters; physical posture checks require operator consent.
