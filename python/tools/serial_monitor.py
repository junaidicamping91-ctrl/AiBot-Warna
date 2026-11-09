#!/usr/bin/env python3
"""Monitor serial manual untuk uji Arduino (Chapter 2.3).

    python python/tools/serial_monitor.py --port COM3
    > T,25,-10,1,90      (kirim error bidikan + warna MERAH)
    > BUZZ,3             (tes melodi BIRU)
    > RGB,255,0,0        (tes LED)
    > CENTER / PING / GAIN,0.2,0.005,0.03
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_DIR))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    a = ap.parse_args()
    try:
        import serial  # type: ignore
    except ImportError:
        print("pyserial belum ada: pip install pyserial")
        return 1

    try:
        ser = serial.Serial(a.port, a.baud, timeout=0.1)
    except Exception as exc:
        print(f"Gagal buka {a.port}: {exc}")
        return 1
    time.sleep(1.8)
    print(f"Terhubung {a.port} @ {a.baud}. Ketik perintah, 'quit' untuk keluar.")

    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                if ser.in_waiting:
                    line = ser.readline().decode("utf-8", "ignore").strip()
                    if line:
                        print(f"  <- {line}")
            except Exception:
                break
            time.sleep(0.02)

    threading.Thread(target=reader, daemon=True).start()
    try:
        while True:
            cmd = input("> ").strip()
            if cmd.lower() in ("quit", "exit", "q"):
                break
            if cmd:
                ser.write((cmd + "\n").encode("ascii"))
                print(f"  -> {cmd}")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        stop.set()
        ser.write(b"CENTER\n")
        time.sleep(0.05)
        ser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
