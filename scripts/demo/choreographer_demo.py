#!/usr/bin/env python3
# ruff: noqa: E402, T201
"""
Demo script showing how to test choreographer with simulated events.

This script demonstrates the choreographer in action by publishing
test sentiment events to the bus.

Usage:
    # Terminal 1: Start the choreographer
    python3 -m apps.choreographer

    # Terminal 2: Start motion module (to see motion commands)
    python3 -m apps.motion.main

    # Terminal 3: Run this demo
    python3 scripts/demo/choreographer_demo.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Add project root to path
repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

from common.bus import BusPub, BusSub


def demo_sentiment_events() -> None:
    """Publish sample sentiment events to demonstrate choreography."""
    print("=" * 60)
    print("Choreographer Demo - Sentiment Events")
    print("=" * 60)
    print()
    print("This demo publishes sentiment events that trigger choreographies.")
    print("Make sure the choreographer is running in another terminal.")
    print()

    pub = BusPub(warmup_ms=100)

    sentiments = [
        ("joy", "Triggering JOY choreography..."),
        ("sad", "Triggering SAD choreography..."),
        ("neutral", "Triggering NEUTRAL choreography..."),
        ("joy", "Triggering JOY again..."),
    ]

    try:
        for sentiment, description in sentiments:
            print(f"\n{description}")
            payload = {"sentiment": sentiment, "confidence": 0.9, "source": "demo"}
            pub.publish("events.sentiment", payload, add_ts=True)
            print(f"  Published: events.sentiment → {payload}")
            print("  Expected choreography:")
            if sentiment == "joy":
                print("    - Face: happy expression")
                print("    - Motion: drive forward (lx=0.3)")
            elif sentiment == "sad":
                print("    - Face: sad expression")
            else:
                print("    - Face: neutral expression")

            time.sleep(3)  # Wait between events

        print("\n" + "=" * 60)
        print("Demo complete!")
        print("=" * 60)

    finally:
        pub.close()


def demo_listen_commands() -> None:
    """Listen to commands published by choreographer."""
    print("=" * 60)
    print("Choreographer Demo - Command Listener")
    print("=" * 60)
    print()
    print("Listening for commands from choreographer...")
    print("Press Ctrl+C to stop.")
    print()

    # Subscribe to all command topics and motion
    sub = BusSub(["command", "motion"])

    try:
        while True:
            topic, payload = sub.recv(timeout_ms=1000)
            if topic and payload:
                print(f"\n[{time.strftime('%H:%M:%S')}] Received command:")
                print(f"  Topic: {topic}")
                print(f"  Payload: {payload}")

    except KeyboardInterrupt:
        print("\nStopped listening.")

    finally:
        sub.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Choreographer demo")
    parser.add_argument(
        "mode",
        choices=["publish", "listen"],
        help="publish: send test events; listen: monitor commands",
    )

    args = parser.parse_args()

    if args.mode == "publish":
        demo_sentiment_events()
    else:
        demo_listen_commands()
