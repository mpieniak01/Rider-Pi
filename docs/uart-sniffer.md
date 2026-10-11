# Optional UART sniffer

The tap observes the existing UART owner. It never opens a second port, reads
extra registers, changes arming, or sends robot commands. Recording is disabled
by default. Attach/detach controls must run as the same operating-system user.

~~~sh
python3 scripts/uart_sniffer.py list
python3 scripts/uart_sniffer.py attach --pid PID --seconds 60
python3 scripts/uart_sniffer.py status --pid PID
python3 scripts/uart_sniffer.py detach --pid PID
~~~

Status returns the exact capture path. Private JSONL captures live in
/tmp/rider-uart-sniffer-UID with mode 600. Sessions last 1–300 seconds with an
8 MiB limit and a bounded 1024-event queue. Overflow drops records rather than
blocking UART. The final event reports drops, including queued events discarded
at detach. Multiple sessions have no shared storage cap; manage files manually.

## Offline decoding and analysis

~~~sh
python3 scripts/uart_sniffer.py decode capture.jsonl --firmware R-1.1.6 > frames.jsonl
python3 scripts/uart_sniffer.py analyze capture.jsonl --firmware R-1.1.6 \
  --output report.json --markdown report.md
~~~

The report includes frame checksums, raw payloads, host chunk times, named
registers, command changes, write intervals, sensor ranges and read transactions.
It decodes action IDs, performance, balance, height/roll setpoints, periodic
generators, neutral command byte 128, battery, work status and the confirmed
R-1.1.6 IMU packet. Acceleration includes gravity. SDK-mapped setpoints are
not measured positions; command bytes are not physical velocity.

The controller format comes from an observed firmware response or an explicit
--firmware argument. Earlier samples with unknown format remain raw.
Action labels are documentation mappings, not hardware validation.
Writes do not confirm reception or physical execution. ActionTime is not an ACK.

Read pairing uses address, length and an observation window (100 ms by default,
--response-timeout-ms). This is an analysis setting, not a motion timeout.
Overlapping identical reads are marked ambiguous. Late identical responses
cannot always be distinguished, since the protocol has no transaction IDs.

## Observation limits and deeper capture

SerialTap observes serial calls, not every byte on the wire. Flushes create
continuity gaps whose discarded data is unknown. TX records accepted serial
writes; RX records data read by the owner. Constructor reads precede tap
installation. The tap does not correlate HTTP request IDs.

An external logic analyzer on the Pi/controller UART can capture discarded
bytes and wire timing. A separate tap on the controller/motor bus is needed
for internal commands. Identify the interface, signal levels, pins and
directions from the correct board schematic before connecting equipment.
Do not assume UART, RS485, CAN or voltage levels.

External exports can use JSONL direction tx/rx, hex bytes and monotonic time_ns,
with start/end metadata and gap records. Apply the XGO decoder only to an
interface that actually carries XGO frames; a motor bus may use another protocol.
The report identifies input provenance separately from serial-call timing.

## Vendor application

Only in an operator-approved actuator session, release the existing UART owner
and run the vendor application using its original working directory/interpreter:

~~~sh
python3 /home/pi/robot/scripts/uart_sniffer_vendor.py --operator-session /home/pi/RaspberryPi-CM4-main/app/app_TwoCar.py
~~~

This executes vendor code, which may reset posture or move the robot. It is
not protected by Rider-Pi's motion gate. Never run it in CI/unit tests.
Use list/attach/status/detach from another terminal. Calls before attach
are not captured. The launcher does not modify vendor files or global packages.

One background thread serves recording and its local socket. Capture failure
must not alter serial results. Detach needs no restart; offline analyzer updates
need no executor restart. Changing tap installation requires restarting its owner.

External XGO export example / Przykład zewnętrznego eksportu XGO:

~~~sh
python3 scripts/uart_sniffer.py analyze wire.jsonl --source wire_export --firmware R-1.1.6 --output wire-report.json
~~~
