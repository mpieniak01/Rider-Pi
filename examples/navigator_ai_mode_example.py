#!/usr/bin/env python3
"""
Example: Navigator Module AI Mode Adaptation

This demonstrates how navigator modules should adapt to AI mode changes.
When in pc_offload mode, navigator should subscribe to enhanced obstacle
data from the PC instead of using only local obstacle detection.

Integration points:
1. Check ai_mode.is_offload() to determine data source
2. Subscribe to TOPIC_VISION_OBSTACLE_ENHANCED for PC results
3. Merge or prioritize enhanced data when available
"""

from __future__ import annotations

import time

from common import ai_mode
from common.bus import TOPIC_VISION_OBSTACLE, TOPIC_VISION_OBSTACLE_ENHANCED, BusSub


def navigator_loop():
    """
    Example navigator loop that adapts to AI mode.

    In local mode: Use local obstacle detection only
    In pc_offload mode: Prefer enhanced obstacle data from PC
    """
    local_obstacle_sub = BusSub(TOPIC_VISION_OBSTACLE)
    enhanced_obstacle_sub = BusSub(TOPIC_VISION_OBSTACLE_ENHANCED)

    print("[navigator] Starting adaptive navigation...")

    while True:
        obstacle_data = None

        # Check current mode
        if ai_mode.is_offload():
            # PC OFFLOAD MODE: Prefer enhanced obstacle data from PC
            print("[navigator] PC offload mode - using enhanced obstacle data from PC...")

            # Try to get enhanced data first (with timeout)
            topic, payload = enhanced_obstacle_sub.recv(timeout_ms=100)
            if topic and payload:
                obstacle_data = payload
                print(f"[navigator] Using enhanced obstacle data: {obstacle_data}")
            else:
                # Fallback to local if PC data not available
                topic, payload = local_obstacle_sub.recv(timeout_ms=100)
                if topic and payload:
                    obstacle_data = payload
                    print("[navigator] No PC data, using local obstacle data (fallback)")

        else:
            # LOCAL MODE: Use local obstacle detection
            print("[navigator] Local mode - using local obstacle detection...")

            topic, payload = local_obstacle_sub.recv(timeout_ms=100)
            if topic and payload:
                obstacle_data = payload
                print(f"[navigator] Using local obstacle data: {obstacle_data}")

        # Process obstacle data and plan path
        if obstacle_data:
            present = obstacle_data.get("present", False)
            if present:
                print("[navigator] Obstacle detected - planning avoidance")
                # plan_avoidance()
            else:
                print("[navigator] Path clear - continuing")
                # continue_path()
        else:
            print("[navigator] No obstacle data available")

        time.sleep(0.5)


def path_planning_example():
    """
    Example showing how path planning can benefit from enhanced PC data.

    Enhanced data from PC might include:
    - 3D depth information
    - Better object classification
    - Predictive movement analysis
    - Higher accuracy obstacle boundaries
    """
    if ai_mode.is_offload():
        print("[pathfinding] Using enhanced path planning with PC data")
        # Enhanced path planning with better obstacle information
        # - Use depth data for 3D obstacle mapping
        # - Use object classification for smarter avoidance
        # - Use predictive data for dynamic obstacles
    else:
        print("[pathfinding] Using local path planning")
        # Basic path planning with local 2D obstacle detection


if __name__ == "__main__":
    try:
        navigator_loop()
    except KeyboardInterrupt:
        print("\n[navigator] Shutting down...")
