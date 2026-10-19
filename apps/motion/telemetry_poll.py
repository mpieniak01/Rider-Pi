"""One bounded sensor transaction per executor pass; optional reads never grant motion."""

from apps.motion.sensor_quality import AXES


def poll(executor):
    if not executor._hardware_ready():
        # This owner also receives the legacy "motion" prefix. A forced
        # state publish here feeds its own subscription and spins on failure.
        executor.publish_status()
        return
    now = executor.gate.clock()
    if now - executor.last_sensors < 0.1:
        return
    executor.last_sensors = now
    adapter = executor.adapter
    reader = getattr(adapter, "read_sensor", None)
    if callable(reader):
        _poll_named_sensor(executor, adapter, reader, now)
    else:
        _poll_legacy_sensors(executor, adapter, now)
    executor._publish("motion.sensor.raw", executor.samples.payload(executor.firmware))


def _poll_named_sensor(executor, adapter, reader, now):
    if now - executor.last_firmware >= 30:
        name = "firmware"
        executor.last_firmware = now
    else:
        schedule = (
            ("imu_packet", "battery", "work_status")
            if getattr(adapter, "extended_sensor_reads", False)
            else ("roll", "pitch", "yaw", "battery")
        )
        name = schedule[executor.sensor_index % len(schedule)]
        executor.sensor_index += 1
    measured_at = executor.gate.wall_clock()
    value = reader(name)
    executor.sensor_values[name] = value
    executor.sensor_times[name] = now
    _observe_named_sensor(executor, name, value, measured_at, now)
    executor.firmware = executor.sensor_values.get("firmware")


def _observe_named_sensor(executor, name, value, measured_at, now):
    names = (*AXES, "accel_x", "accel_y", "accel_z")
    if name == "imu_packet":
        for channel in names:
            executor.samples.observe(
                channel,
                value.get(channel) if isinstance(value, dict) else None,
                measured_at=measured_at,
                monotonic_at=now,
            )
    elif name in (*AXES, "battery", "work_status"):
        executor.samples.observe(name, value, measured_at=measured_at, monotonic_at=now)


def _poll_legacy_sensors(executor, adapter, now):
    imu = adapter.get_imu()
    executor.firmware = adapter.firmware()
    for name in AXES:
        executor.samples.observe(name, imu.get(name) if isinstance(imu, dict) else None, monotonic_at=now)
    executor.samples.observe("battery", adapter.battery(), monotonic_at=now)
