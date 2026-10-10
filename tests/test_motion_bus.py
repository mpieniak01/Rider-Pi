#!/usr/bin/env python3
"""Legacy direct actuation is disabled; explicit operator probes use the API."""


def main():
    raise SystemExit(
        "Automatic movement sequence disabled. Use scripts/manual_motion-probe.py "
        "for one prepared, operator-approved attempt."
    )


if __name__ == "__main__":
    main()
