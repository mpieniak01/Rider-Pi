# Extended Rider-Pi telemetry

Confirmed on controller R-1.1.6: register 0x65 returns 24 bytes,
six little-endian float32 values: acceleration XYZ and roll/pitch/yaw.
Acceleration includes gravity; physical axis orientation still needs validation.
This is neither wheel velocity nor angular velocity.

Register 0x02: 0 = fallen, 1 = normal according to the manufacturer table.
The register is informational and does not change motion authorization.

A single UART owner, motion-executor, reads the sensors. On R-1.1.6 the
packet replaces three individual angle reads. Other firmware keeps the
existing polling schedule. Optional accel_x/y/z (m/s^2) and work_status
(code) fields retain measurement time, source and quality in rider.telemetry v1.
Missing optional fields never block motion.
Overview consumes this shared contract without opening UART.

UI label: Accelerometer XYZ (m/s², including gravity). Separate IMU angles
describe orientation; XYZ is not gravity-compensated driving acceleration.
