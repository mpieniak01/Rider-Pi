#!/usr/bin/env python3
from __future__ import annotations

"""
apps/choreographer/main.py — Choreographer service

Orchestrates synchronized actions across face, motion, and voice modules.
Subscribes to events (e.g., sentiment/emotion) and publishes choreographed
commands to multiple modules.

Example flow:
  Input:  SUB("events.sentiment") → {"sentiment": "joy", "confidence": 0.9}
  Output: PUB("command.face.expression") → {"expression": "happy"}
          PUB("motion") → {"type": "drive", "lx": 0.3, "az": 0.0}
"""

import logging
import os
import signal
import sys
import time
from pathlib import Path

from common.bus import BusPub, BusSub

# Ensure project root is in path

# Configure logging
LOG_LEVEL = os.getenv("CHOREOGRAPHER_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="[%(asctime)s] [choreographer] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
LOG = logging.getLogger("choreographer")

# Configuration
CONFIG_PATH = os.getenv("CHOREOGRAPHER_CONFIG", None)
WARMUP_MS = int(os.getenv("CHOREOGRAPHER_WARMUP_MS", "10"))


def log(msg: str):
    """Log message with timestamp."""
    LOG.info(msg)


def match_event(event_payload: dict, match_criteria: dict) -> bool:
    """
    Check if event payload matches trigger criteria.
    
    Args:
        event_payload: The received event data
        match_criteria: Dictionary of field: value pairs to match
    
    Returns:
        True if all criteria match, False otherwise
    """
    for field, expected_value in match_criteria.items():
        if field not in event_payload:
            return False
        
        actual_value = event_payload[field]
        
        # Support wildcards and partial matching
        if expected_value == "*":
            continue
        
        # For lists, check if actual is in list
        if isinstance(expected_value, list):
            if actual_value not in expected_value:
                return False
        # For exact match
        elif actual_value != expected_value:
            return False
    
    return True


def execute_action(pub: BusPub, action: dict):
    """
    Execute a choreographed action by publishing to the appropriate topic.
    
    Args:
        pub: BusPub instance for publishing
        action: Action configuration with 'topic' and 'payload'
    """
    topic = action.get("topic")
    payload = action.get("payload", {})
    
    if not topic:
        LOG.warning("Action missing 'topic' field, skipping")
        return
    
    try:
        pub.publish(topic, payload, add_ts=True)
        LOG.debug(f"Published to {topic}: {payload}")
    except Exception as e:
        LOG.error(f"Failed to publish to {topic}: {e}")


def process_event(topic: str, payload: dict, mappings: list, pub: BusPub):
    """
    Process an incoming event and execute matching choreographies.
    
    Args:
        topic: The topic the event was received on
        payload: The event payload
        mappings: List of choreography mappings
        pub: BusPub instance for publishing commands
    """
    for mapping in mappings:
        trigger = mapping.get("trigger", {})
        trigger_topic = trigger.get("topic", "")
        match_criteria = trigger.get("match", {})
        
        # Check if topic matches (support prefix matching with .*)
        topic_matches = False
        if trigger_topic.endswith(".*"):
            prefix = trigger_topic[:-2]
            topic_matches = topic.startswith(prefix)
        else:
            topic_matches = topic == trigger_topic
        
        if not topic_matches:
            continue
        
        # Check if payload matches criteria
        if not match_event(payload, match_criteria):
            continue
        
        # Execute all actions for this mapping
        actions = mapping.get("actions", [])
        LOG.info(f"Choreography triggered by {topic}: executing {len(actions)} action(s)")
        
        for action in actions:
            execute_action(pub, action)


def main():
    """Main choreographer service loop."""
    # Load configuration
    from apps.choreographer.config import load_choreography_config, validate_config
    
    try:
        config = load_choreography_config(CONFIG_PATH)
    except Exception as e:
        LOG.error(f"Failed to load configuration: {e}")
        sys.exit(1)
    
    if not validate_config(config):
        LOG.error("Invalid configuration structure")
        sys.exit(1)
    
    mappings = config.get("mappings", [])
    LOG.info(f"Loaded {len(mappings)} choreography mapping(s)")
    
    # Collect all topics to subscribe to
    topics_to_subscribe = set()
    for mapping in mappings:
        trigger_topic = mapping.get("trigger", {}).get("topic", "")
        if trigger_topic:
            # For wildcard topics, subscribe to the prefix
            if trigger_topic.endswith(".*"):
                topics_to_subscribe.add(trigger_topic[:-2])
            else:
                topics_to_subscribe.add(trigger_topic)
    
    if not topics_to_subscribe:
        LOG.warning("No topics to subscribe to. Check configuration.")
        # Still run but will be idle
        topics_to_subscribe.add("events")  # Subscribe to base events topic
    
    LOG.info(f"Subscribing to topics: {', '.join(sorted(topics_to_subscribe))}")
    
    # Initialize bus
    sub = BusSub(list(topics_to_subscribe))
    pub = BusPub(warmup_ms=WARMUP_MS)
    
    # Signal handling
    running = [True]
    
    def signal_handler(_sig, _frame):
        LOG.info("Received shutdown signal")
        running[0] = False
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    LOG.info("Choreographer started")
    
    # Main loop
    try:
        while running[0]:
            topic, payload = sub.recv(timeout_ms=1000)
            
            if topic is None or payload is None:
                continue
            
            try:
                process_event(topic, payload, mappings, pub)
            except Exception as e:
                LOG.error(f"Error processing event from {topic}: {e}")
    
    except KeyboardInterrupt:
        pass
    finally:
        LOG.info("Shutting down choreographer")
        pub.close()
        sub.close()


if __name__ == "__main__":
    main()
