#!/usr/bin/env python3
# tests/test_motion_bus.py
"""
Tester ścieżki BUS → motion.main → adapter → robot.

Wysyła komendy na topic 'motion.cmd' i (jeśli dostępne) nasłuchuje 'motion.echo'.
Domyślne adresy busa:
  PUB: tcp://127.0.0.1:5555  (ENV: BUS_PUB)
  SUB: tcp://127.0.0.1:5556  (ENV: BUS_SUB)

Uruchom:
  MOTION_ENABLE=1 python3 tests/test_motion_bus.py
Uwaga: pętla apps.motion.main musi być uruchomiona.
"""

import os, time, json, zmq

PUB_ADDR = os.getenv("BUS_PUB", "tcp://127.0.0.1:5555")
SUB_ADDR = os.getenv("BUS_SUB", "tcp://127.0.0.1:5556")
CMD_TOPIC  = "motion.cmd"
ECHO_TOPIC = "motion.echo"

def main():
    ctx = zmq.Context.instance()
    pub = ctx.socket(zmq.PUB); pub.connect(PUB_ADDR)
    sub = ctx.socket(zmq.SUB); sub.connect(SUB_ADDR); sub.setsockopt_string(zmq.SUBSCRIBE, ECHO_TOPIC)
    time.sleep(0.2)  # daj busowi czas

    def send(obj):
        msg = json.dumps(obj, separators=(",",":"))
        pub.send_string(f"{CMD_TOPIC} {msg}")

    def wait_echo(timeout_ms=800):
        poller = zmq.Poller(); poller.register(sub, zmq.POLLIN)
        socks = dict(poller.poll(timeout_ms))
        if sub in socks and socks[sub] == zmq.POLLIN:
            t, payload = sub.recv_string().split(" ", 1)
            print("[echo]", payload)
            return True
        return False

    print("[TEST] STOP")
    send({"type":"stop"}); wait_echo()

    print("\n[TEST] Naprzód 0.3s")
    send({"type":"drive","lx":0.15,"az":0.0}); time.sleep(0.3)
    send({"type":"stop"}); wait_echo()

    print("\n[TEST] Wstecz 0.3s")
    send({"type":"drive","lx":-0.15,"az":0.0}); time.sleep(0.3)
    send({"type":"stop"}); wait_echo()

    print("\n[TEST] Obrót w LEWO 0.5s (az<0)")
    send({"type":"drive","lx":0.0,"az":-0.35}); time.sleep(0.5)
    send({"type":"stop"}); wait_echo()

    print("\n[TEST] Obrót w PRAWO 0.5s (az>0)")
    send({"type":"drive","lx":0.0,"az":+0.35}); time.sleep(0.5)
    send({"type":"stop"}); wait_echo()

    # (opcjonalnie) jeżeli motion.main obsługuje komendę 'spin':
    print("\n[TEST] Spin LEFT 0.5s (komenda 'spin' jeśli wspierana)")
    send({"type":"spin","dir":"left","speed":0.4,"dur":0.5}); wait_echo(1200)

    print("\n[TEST] Spin RIGHT 0.5s (komenda 'spin' jeśli wspierana)")
    send({"type":"spin","dir":"right","speed":0.4,"dur":0.5}); wait_echo(1200)

    print("\n[DONE] Test przez bus zakończony.")

if __name__ == "__main__":
    main()
