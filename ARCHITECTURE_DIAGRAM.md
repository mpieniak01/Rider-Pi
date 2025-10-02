# Simulator Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         RIDER-PI 2D SIMULATOR                       │
└─────────────────────────────────────────────────────────────────────┘

┌──────────────────────┐
│   Control Sources    │
├──────────────────────┤
│ • Keyboard Control   │──┐
│ • Manual Commands    │  │
│ • Motion Planning    │  │
│ • Web Interface      │  │
└──────────────────────┘  │
                          │
                          ▼
                    ┌──────────┐
                    │   PUB    │ tcp://127.0.0.1:5555
                    └────┬─────┘
                         │
                         ▼
            ┌────────────────────────┐
            │     ZMQ BROKER         │
            │   (XSUB ↔ XPUB)        │
            └────────────┬───────────┘
                         │
                         ▼
                    ┌──────────┐
                    │   SUB    │ tcp://127.0.0.1:5556
                    └────┬─────┘
                         │
         ┌───────────────┴────────────────┐
         │                                 │
         ▼                                 ▼
┌─────────────────┐            ┌──────────────────┐
│ SimulatedRobot  │            │  Motion System   │
├─────────────────┤            │  (apps/motion)   │
│ • recv_commands │            └──────────────────┘
│ • update(dt)    │
│ • get_state()   │
└────────┬────────┘
         │
         ├─────────► Position (x, y)
         ├─────────► Orientation (angle)
         └─────────► Velocities (linear, angular)
                         │
         ┌───────────────┴───────────────┐
         │                               │
         ▼                               ▼
┌─────────────────┐            ┌─────────────────┐
│  VirtualGyro    │            │ VirtualCamera   │
├─────────────────┤            ├─────────────────┤
│ Publishes:      │            │ • Raycasting    │
│ • yaw           │            │ • First-person  │
│ • roll          │            │   view          │
│ • pitch         │            │ Publishes:      │
│ @ 10 Hz         │            │ • Frame data    │
└─────────────────┘            │ @ 5 Hz          │
                               └─────────────────┘
         │                               │
         └───────────────┬───────────────┘
                         │
                         ▼
                    ┌──────────┐
                    │   PUB    │ tcp://127.0.0.1:5555
                    └────┬─────┘
                         │
                         ▼
            ┌────────────────────────┐
            │   Monitoring Systems   │
            │   • Telemetry Display  │
            │   • Data Logging       │
            │   • Web Dashboard      │
            └────────────────────────┘


┌─────────────────────────────────────────────────────────────────────┐
│                         RENDERING PIPELINE                          │
└─────────────────────────────────────────────────────────────────────┘

┌──────────────┐
│   World      │
├──────────────┤
│ • Load map   │
│ • Parse 'R'  │
│ • Extract    │
│   walls      │
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────────┐
│         Pygame Window                │
├──────────────────────────────────────┤
│  ┌────────────────┬───────────────┐  │
│  │   Map View     │  Telemetry    │  │
│  │                │  Panel        │  │
│  │  ########      │               │  │
│  │  #  🤖  #      │  X: 5.23 m   │  │
│  │  #      #      │  Y: 3.45 m   │  │
│  │  ########      │  θ: 45.2°    │  │
│  │                │               │  │
│  │                │  v: 0.30 m/s │  │
│  │                │  ω: 0.75 r/s │  │
│  │                │               │  │
│  │                │  ┌──────────┐ │  │
│  │                │  │ Camera   │ │  │
│  │                │  │ View     │ │  │
│  │                │  └──────────┘ │  │
│  └────────────────┴───────────────┘  │
└──────────────────────────────────────┘
         │
         ▼
    @ 60 FPS


┌─────────────────────────────────────────────────────────────────────┐
│                      PHYSICS SIMULATION                             │
└─────────────────────────────────────────────────────────────────────┘

Input: Command {type: "drive", lx: 1.0, az: 0.5}
   │
   ▼
Scale Velocities:
   v_linear = lx × 0.3 m/s
   v_angular = az × 1.5 rad/s
   │
   ▼
Update @ 60 Hz (dt = 0.0167s):
   θ ← θ + v_angular × dt
   θ ← normalize(θ)  // [-π, π]
   x ← x + v_linear × cos(θ) × dt
   y ← y + v_linear × sin(θ) × dt
   │
   ▼
New State: {x: 5.23, y: 3.45, θ: 0.79, v: 0.3, ω: 0.75}


┌─────────────────────────────────────────────────────────────────────┐
│                        MESSAGE FORMAT                               │
└─────────────────────────────────────────────────────────────────────┘

ZMQ Multipart: [topic_bytes, payload_bytes]

Drive Command:
┌────────────────────────────────────────┐
│ Topic: "motion"                        │
│ Payload: {                             │
│   "type": "drive",                     │
│   "lx": 1.0,   // -1.0 to 1.0         │
│   "az": 0.5    // -1.0 to 1.0         │
│ }                                      │
└────────────────────────────────────────┘

Stop Command:
┌────────────────────────────────────────┐
│ Topic: "motion"                        │
│ Payload: {                             │
│   "type": "stop"                       │
│ }                                      │
└────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────┐
│                           FILE STRUCTURE                            │
└─────────────────────────────────────────────────────────────────────┘

sim/
├── __init__.py              # Module initialization
├── robot.py                 # SimulatedRobot class
├── world.py                 # World class (map, rendering)
├── sensors.py               # VirtualGyro, VirtualCamera
├── README.md                # User documentation
└── maps/
    └── simple.txt           # Sample map file

run_simulation.py            # Main entry point

tools/
└── sim_keyboard_control.py  # Keyboard control (WASD)

tests/
├── test_simulator_robot.py  # Unit tests (7 tests)
├── test_simulator_mqtt.py   # Integration test
└── test_simulator_init.py   # Headless test

demo_simulator.sh            # Demo script
IMPLEMENTATION_SUMMARY.md    # Technical documentation
```
