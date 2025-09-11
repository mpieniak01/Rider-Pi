#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XGOClientRO — lekka biblioteka 'read-only' do odczytu sensorów XGO.
- Zero komend ruchu (bezpieczna dla robota)
- Własny parser ramek zgodny z xgolib (__unpack)
- Testowy CLI: --port /dev/ttyAMA0 --loop --verbose
"""

import serial, time, struct, threading
from typing import Optional, List

# Adresy rejestrów (jak w xgolib)
ADDR = {
    "BATTERY": 0x01,
    "FIRMWARE": 0x07,
    "ROLL": 0x62,
    "PITCH": 0x63,
    "YAW": 0x64,
    "IMU_FLOATS": 0x65,
    "ROLL_I16": 0x66,
    "PITCH_I16": 0x67,
    "YAW_I16": 0x68,
}

# Biała lista odczytów (adres, oczekiwana minimalna długość payloadu)
READ_WHITELIST = {
    (ADDR["BATTERY"], 1),
    (ADDR["FIRMWARE"], 10),
    (ADDR["ROLL"], 4),
    (ADDR["PITCH"], 4),
    (ADDR["YAW"], 4),
    (ADDR["IMU_FLOATS"], 24),
    (ADDR["ROLL_I16"], 2),
    (ADDR["PITCH_I16"], 2),
    (ADDR["YAW_I16"], 2),
}

def _checksum(length: int, type_: int, addr: int, payload: bytes) -> int:
    s = (length + type_ + addr + sum(payload)) % 256
    return (255 - s) & 0xFF

def _byte2float_le_as_net_order(raw4: bytes) -> float:
    # xgolib składa float jako [b3,b2,b1,b0] i używa "!f"
    a = bytearray([raw4[3], raw4[2], raw4[1], raw4[0]])
    return struct.unpack("!f", a)[0]

def _byte2short_be(raw2: bytes) -> int:
    return struct.unpack(">h", raw2[:2])[0]

class XGOClientRO:
    def __init__(self, port: str = "/dev/ttyAMA0", baud: int = 115200, timeout: float = 0.6, verbose: bool = False):
        self._ser = serial.Serial(port, baud, timeout=timeout)
        self._lock = threading.Lock()
        self.verbose = verbose

    def close(self):
        try: self._ser.close()
        except Exception: pass

    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): self.close()

    def _read_cmd(self, addr: int, read_len: int, timeout: float = 0.9) -> Optional[bytes]:
        """Wyślij ramkę READ (0x02) i sparsuj odpowiedź — zgodnie z xgolib."""
        if (addr, read_len) not in READ_WHITELIST:
            if self.verbose:
                print(f"[XGO-RO] blocked read addr={hex(addr)} len={read_len}")
            return None

        mode = 0x02         # READ
        length = 0x09       # stała w ich protokole dla odczytu
        chk = _checksum(length, mode, addr, bytes([read_len]))
        tx = bytes([0x55, 0x00, length, mode, addr, read_len, chk, 0x00, 0xAA])

        with self._lock:
            self._ser.reset_input_buffer()
            if self.verbose: print("[tx]", tx.hex())
            self._ser.write(tx)

            start = time.time()
            stage = 0
            rx_len = 0
            rx_type = 0
            rx_addr = 0
            payload = bytearray()

            while time.time() - start < timeout:
                b = self._ser.read(1)
                if not b:
                    continue
                x = b[0]

                if stage == 0:      # 0x55
                    stage = 1 if x == 0x55 else 0
                elif stage == 1:    # 0x00
                    stage = 2 if x == 0x00 else 0
                elif stage == 2:    # LEN
                    rx_len = x
                    stage = 3
                elif stage == 3:    # TYPE
                    rx_type = x     # nie wymuszamy == 0x02
                    stage = 4
                elif stage == 4:    # ADDR
                    rx_addr = x
                    payload.clear()
                    # KLUCZ: w xgolib payload ma długość (LEN - 8)
                    need_len = max(0, rx_len - 8)
                    stage = 5
                elif stage == 5:    # PAYLOAD
                    payload.append(x)
                    if len(payload) >= need_len:
                        stage = 6
                elif stage == 6:    # CHECK
                    rx_check = x
                    calc = _checksum(rx_len, rx_type, rx_addr, payload)
                    if rx_check == calc:
                        stage = 7
                    else:
                        if self.verbose:
                            print("[warn] checksum mismatch")
                        stage = 0
                        payload.clear()
                elif stage == 7:    # 0x00
                    stage = 8 if x == 0x00 else 0
                elif stage == 8:    # 0xAA
                    if x == 0xAA:
                        if self.verbose:
                            print(f"[rx] len={rx_len} type=0x{rx_type:02X} addr=0x{rx_addr:02X} pl={payload.hex()}")
                        if rx_addr != addr:
                            return None
                        # Nie wymuszamy, że need_len == read_len (bywa „pełny” bufor)
                        if len(payload) < read_len:
                            return None
                        return bytes(payload[:read_len])
                    stage = 0
            return None

    # --- Publiczne metody odczytu ---

    def read_battery(self) -> Optional[int]:
        pl = self._read_cmd(ADDR["BATTERY"], 1)
        return int(pl[0]) if pl else None

    def read_firmware(self) -> Optional[str]:
        pl = self._read_cmd(ADDR["FIRMWARE"], 10)
        return pl.decode("ascii", "ignore").strip("\0") if pl else None

    def read_roll(self) -> Optional[float]:
        pl = self._read_cmd(ADDR["ROLL"], 4)
        return round(_byte2float_le_as_net_order(pl), 2) if pl else None

    def read_pitch(self) -> Optional[float]:
        pl = self._read_cmd(ADDR["PITCH"], 4)
        return round(_byte2float_le_as_net_order(pl), 2) if pl else None

    def read_yaw(self) -> Optional[float]:
        pl = self._read_cmd(ADDR["YAW"], 4)
        return round(_byte2float_le_as_net_order(pl), 2) if pl else None

    def read_imu(self) -> Optional[List[float]]:
        """Zwraca [ax, ay, az, gx, gy, gz, roll(rad), pitch(rad), yaw(rad)]"""
        pl = self._read_cmd(ADDR["IMU_FLOATS"], 24, timeout=1.0)
        if not pl or len(pl) < 24:
            return None
        out = []
        # 0..5: int16 (ax,ay,az,gx,gy,gz)
        for i in range(6):
            hi, lo = pl[2*i+1], pl[2*i]
            val = struct.unpack("!h", bytes([hi, lo]))[0]
            if i < 3:
                out.append(val / 16384.0 * 9.8)
            else:
                out.append(val / 16.4)
        # 6..8: float32 (roll,pitch,yaw) — w radianach
        for i in range(3):
            base = 12 + 4*i
            out.append(struct.unpack("!f", pl[base:base+4])[0])
        return out

    def read_imu_int16(self, direction: str) -> Optional[int]:
        if direction == "roll":   addr = ADDR["ROLL_I16"]
        elif direction == "pitch":addr = ADDR["PITCH_I16"]
        elif direction == "yaw":  addr = ADDR["YAW_I16"]
        else: return None
        pl = self._read_cmd(addr, 2)
        return _byte2short_be(pl) if pl else None


# ----- tryb CLI/testowy -----
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyAMA0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args()

    def one(x: XGOClientRO):
        fw = x.read_firmware()
        bt = x.read_battery()
        r = x.read_roll(); p = x.read_pitch(); y = x.read_yaw()
        print(f"fw={fw} batt={bt}% r={r} p={p} y={y}")

    with XGOClientRO(args.port, args.baud, verbose=args.verbose) as x:
        if args.loop:
            print("[loop] CTRL+C aby zakończyć")
            try:
                while True:
                    one(x); time.sleep(1.0)
            except KeyboardInterrupt:
                pass
        else:
            one(x)
