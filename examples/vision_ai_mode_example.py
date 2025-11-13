#!/usr/bin/env python3
"""
Example: Vision Module AI Mode Adaptation

This demonstrates how vision modules should adapt to AI mode changes.
When in pc_offload mode, local detectors should be disabled and the module
should subscribe to enhanced results from the PC.

Integration points:
1. Check ai_mode.is_offload() before running local detectors
2. Subscribe to TOPIC_VISION_OBSTACLE_ENHANCED for PC results
3. Listen for TOPIC_SYSTEM_AI_MODE_CHANGED to react to mode changes
"""

from __future__ import annotations

import time

from common import ai_mode
from common.bus import (
    TOPIC_SYSTEM_AI_MODE_CHANGED,
    TOPIC_VISION_OBSTACLE_ENHANCED,
    BusPub,
    BusSub,
)


def vision_processing_loop():
    """
    Example vision processing loop that adapts to AI mode.

    In local mode: Run local detectors (TFLite, HOG, etc.)
    In pc_offload mode: Subscribe to enhanced results from PC
    """
    pub = BusPub(topic_prefix="vision")
    mode_sub = BusSub(TOPIC_SYSTEM_AI_MODE_CHANGED)
    enhanced_sub = BusSub(TOPIC_VISION_OBSTACLE_ENHANCED)

    print("[vision] Starting adaptive vision processing...")

    while True:
        # Check current mode
        if ai_mode.is_offload():
            # PC OFFLOAD MODE: Disable local detectors, use enhanced results
            print("[vision] PC offload mode - waiting for enhanced results from PC...")

            # Subscribe to enhanced obstacle data
            topic, payload = enhanced_sub.recv(timeout_ms=1000)
            if topic and payload:
                print(f"[vision] Received enhanced obstacle data: {payload}")
                # Forward to local bus if needed
                pub.publish("obstacle.enhanced", payload)

        else:
            # LOCAL MODE: Run local detectors
            print("[vision] Local mode - running local detectors...")

            # Example: Run local detector (TFLite, HOG, etc.)
            # detector_result = run_local_detector()  # Your detector logic here
            detector_result = {"obstacle": False, "confidence": 0.9, "ts": time.time()}

            # Publish local results
            pub.publish("obstacle", detector_result, add_ts=True)

            # Simulate processing time
            time.sleep(0.1)

        # Check for mode changes (non-blocking)
        topic, payload = mode_sub.recv(timeout_ms=10)
        if topic and payload:
            new_mode = payload.get("mode")
            print(f"[vision] AI mode changed to: {new_mode}")
            # React to mode change if needed
            if new_mode == "pc_offload":
                print("[vision] Switching to PC offload mode - stopping local detectors")
                # Clean up local detectors if needed
            elif new_mode == "local":
                print("[vision] Switching to local mode - starting local detectors")
                # Initialize local detectors if needed


if __name__ == "__main__":
    try:
        vision_processing_loop()
    except KeyboardInterrupt:
        print("\n[vision] Shutting down...")
