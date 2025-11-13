# Rider-Pi Apps — PROJECT

> Rider-Pi is the name of the device (hardware). Our project creates independent software **Rider-Pi Apps**, which extends the autonomy and interaction features beyond what the device manufacturer provides.

> Business document (high-level). Presents **project vision and goals** in business-friendly language, with light technical jargon where it aids precision. Implementation details and full architecture will be described in **ARCHITECTURE.md**.

## Project Vision

The project is based on the ready-made Rider-Pi hardware solution. More information about the device can be found on the manufacturer's website: [Yahboom Rider-Pi](https://category.yahboom.net/products/rider-pi-robot). It's a two-wheeled educational robot based on Raspberry Pi 4B, equipped with an HD camera, microphone, 2" LCD screen, stabilizing gyroscope, servo-controlled suspension height adjustment, and drive module. The device runs on Raspberry Pi OS, and software can be developed in Python. Detailed technical specifications are available on the manufacturer's website. It's worth noting that the base version doesn't include a dedicated layer of proximity and collision sensors, which presents a challenge, but also opens opportunities for further development within Rider-Pi Apps.

Rider-Pi Apps is a lightweight, autonomous educational-experimental project. Created for private individuals and technology enthusiasts who want to learn through practice and observation of their own robot's development. It serves as a companion in simple, everyday tasks – moving around, responding to voice, expressing emotions, and clearly presenting its state.

The project is designed to be **energy-efficient** – it operates in short cycles, allowing better battery management and maintaining operational stability. It's developed iteratively, in an educational-experimental phase, using AI tools (ChatGPT, Codex) supporting analysis and development. This way, each successive version is a step toward greater autonomy and better understanding of how technology can cooperate with humans. To realize this vision, we've established the following overarching goals.

## Overarching Goals

1. **Autonomy** – enabling the robot to move independently in various modes:
   - **"Desk" mode** – small movements and maneuvers in a safe, limited space.
   - **"Reconnaissance" mode** – scanning surroundings and building simple maps.
   - **"Follow me" mode** – tracking a person's silhouette or marker and maintaining distance.
2. **Voice Interaction** – responding to short commands, recognizing moments to transition to dialogue, optionally extended with AI service integration supporting conversation.
3. **Emotion Display** – visualizing robot state through simple facial expressions ("smiley face") reflecting the task being performed or conversation progress.
4. **Monitoring and Communication** – ability to track modes and state in web application and on LCD screen.
5. **Safety** – emergency stop mechanisms, obstacle avoidance, speed and movement time limitations.

## Business / User Value

Rider-Pi Apps is an educational and experimental project that combines learning, practice, and creative approach to technology. It allows:

- gaining knowledge in robotics, AI, and human-machine interaction,
- practically testing autonomy concepts on a safe, small scale,
- experiencing interaction with a robot that not only performs tasks but also communicates and expresses emotions.

The project is open and exploratory in nature – development is a discovery process where we verify which solutions prove most valuable and practical. By publishing in a public repository, Rider-Pi Apps also brings value to others: it can inspire, educate, and be an example of an open approach to robotics and AI.

## General Principles

To achieve the above goals, we follow several simple principles:

- Phased development: small, clear iterations instead of large, risky changes.
- Stable foundations: avoiding frequent project direction pivots.
- Simplicity and transparency of operation – both in functions and user communication.
- Conscious energy management – additional modes activated only when needed.

## Milestones (MVP)

To organize project development and step-by-step approach full autonomy, we've established the following stages:

- **M1**: Face ↔ state (emotions, mode panel in UI).
- **M2**: Voice (local commands, AI integration for dialogue as an option).
- **M3**: "Desk" mode + safety (emergency stop, obstacle avoidance).
- **M4**: "Reconnaissance" mode (simple map/trail recording).
- **M5**: "Follow me" mode (distance maintenance).

---
