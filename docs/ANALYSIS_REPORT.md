# Technology Usage Analysis Report

## Executive Summary

This report provides a comprehensive analysis of technology usage in the Rider-Pi project, identifying all key technologies, dependencies, and their usage locations across the codebase.

### Analysis Scope

- **Files Analyzed**: 314
- **Subdirectories Scanned**: apps, services, common, drivers, scripts, tests, sim, config, examples, tools, web, systemd
- **Analysis Date**: 2025-10-29
- **Root Directory**: Excluded (as per requirements)

### Key Findings

The analysis identified **12 major technology categories** across the codebase:

| Technology Category | Files Found | Key Technologies |
|---------------------|-------------|------------------|
| **LLM Technologies** | 49 | OpenAI GPT, Google Gemini, Anthropic Claude |
| **ASR (Speech Recognition)** | 31 | Vosk, OpenAI Whisper, Google Speech |
| **TTS (Text-to-Speech)** | 50 | Piper TTS, OpenAI TTS, Google TTS |
| **NLU (Language Understanding)** | 20 | Custom NLU, Dialogflow integration |
| **Vision Technologies** | 37 | TensorFlow Lite, OpenCV, object detection |
| **Camera Integration** | 120 | Picamera2, V4L2, OpenCV capture |
| **Audio Hardware** | 69 | ALSA, PyAudioALSA, audio capture/playback |
| **Robot Control** | 102 | XGO robot library, motion control |
| **Display Hardware** | 83 | LCD (ILI9xxx), PIL/Pillow, SPI |
| **GPIO and Sensors** | 46 | RPi.GPIO, SPI, I2C sensors |
| **MQTT and Messaging** | 62 | Paho MQTT, ZeroMQ bus |
| **State Management** | 88 | FSM, state transitions, telemetry |

### Major Integration Points

1. **Voice Pipeline**: ASR → Chat (LLM) → TTS with multiple backend support (OpenAI, Google Gemini, local Vosk/Piper)
2. **Vision Pipeline**: Camera → Detection (TFLite/HOG) → LCD display + bus publishing
3. **Robot Control**: MQTT/ZeroMQ bus → Motion module → XGO hardware driver
4. **Multi-modal Interface**: Audio (microphone/speaker), Vision (camera), Display (LCD), Control (buttons)
