"""API observation periods; actuator freshness and watchdog timing are separate."""

SERVICE_STATUS_TTL_S = 2.0
RESOURCE_IDLE_TTL_S = 5.0
RESOURCE_ACTIVE_TTL_S = 3.0


def configure_systemd_observation():
    """Configure the existing shared cache once; do not create a second cache."""
    from common import systemd_snapshot

    systemd_snapshot.TTL_SECONDS = SERVICE_STATUS_TTL_S
