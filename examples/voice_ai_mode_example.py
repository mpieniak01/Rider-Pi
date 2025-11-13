#!/usr/bin/env python3
"""
Example: Voice Module AI Mode Adaptation

This demonstrates how voice modules should adapt to AI mode changes.
When in pc_offload mode, local ASR/TTS/NLU should be disabled and the module
should send/receive data to/from the PC for processing.

Integration points:
1. Check ai_mode.is_offload() before running local ASR/TTS
2. Send raw audio to PC for processing in offload mode
3. Listen for TOPIC_SYSTEM_AI_MODE_CHANGED to react to mode changes
"""

from __future__ import annotations

import time

from common import ai_mode
from common.bus import TOPIC_SYSTEM_AI_MODE_CHANGED, BusPub, BusSub


def voice_processing_loop():
    """
    Example voice processing loop that adapts to AI mode.

    In local mode: Run local ASR/TTS/NLU (Vosk, Piper, etc.)
    In pc_offload mode: Send audio to PC, receive processed results
    """
    pub = BusPub(topic_prefix="voice")
    mode_sub = BusSub(TOPIC_SYSTEM_AI_MODE_CHANGED)

    print("[voice] Starting adaptive voice processing...")

    while True:
        # Check current mode
        if ai_mode.is_offload():
            # PC OFFLOAD MODE: Disable local ASR/TTS, use PC processing
            print("[voice] PC offload mode - sending audio to PC for processing...")

            # Example: Send audio chunk to PC
            audio_chunk = {"audio_data": "base64_encoded_audio", "ts": time.time()}
            pub.publish("audio.raw", audio_chunk)

            # Wait for processed result from PC
            # In real implementation, subscribe to voice.command or voice.transcript topic
            print("[voice] Waiting for processed command from PC...")

            time.sleep(1)

        else:
            # LOCAL MODE: Run local ASR/TTS/NLU
            print("[voice] Local mode - running local ASR/TTS/NLU...")

            # Example: Run local ASR
            # transcript = run_local_asr(audio_chunk)  # Your ASR logic here
            transcript = "example command"

            # Example: Run local NLU
            # intent = run_local_nlu(transcript)  # Your NLU logic here
            intent = {"action": "move", "direction": "forward"}

            # Publish results
            pub.publish("transcript", {"text": transcript, "ts": time.time()})
            pub.publish("intent", intent, add_ts=True)

            # Simulate processing time
            time.sleep(1)

        # Check for mode changes (non-blocking)
        topic, payload = mode_sub.recv(timeout_ms=10)
        if topic and payload:
            new_mode = payload.get("mode")
            print(f"[voice] AI mode changed to: {new_mode}")
            # React to mode change if needed
            if new_mode == "pc_offload":
                print("[voice] Switching to PC offload mode - stopping local ASR/TTS")
                # Clean up local models if needed
            elif new_mode == "local":
                print("[voice] Switching to local mode - loading local models")
                # Initialize local models if needed


def tts_example():
    """Example TTS function that adapts to AI mode"""
    if ai_mode.is_offload():
        print("[tts] PC offload mode - sending text to PC for TTS")
        # Send text to PC via ZMQ
        # pc_tts_client.synthesize(text)
    else:
        print("[tts] Local mode - using local TTS (Piper)")
        # Run local TTS
        # local_tts.synthesize(text)


if __name__ == "__main__":
    try:
        voice_processing_loop()
    except KeyboardInterrupt:
        print("\n[voice] Shutting down...")
