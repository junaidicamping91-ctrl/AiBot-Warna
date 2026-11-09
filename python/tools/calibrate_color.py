#!/usr/bin/env python3
"""Kalibrasi rentang HSV lewat trackbar (Chapter 1.2).

    python python/tools/calibrate_color.py --camera 0 --color-key merah
    python python/main.py --calibrate merah

Arahkan kamera ke benda berwarna, geser 6 trackbar sampai MASK putih hanya
menutupi benda itu, lalu tekan S untuk menyimpan ke config/colors.json.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parents[1]  # berisi utils/, vision/
for _p in (str(PKG_DIR), str(PKG_DIR.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from utils.paths import ROOT, COLORS_FILE, load_json, save_json  # noqa: E402
from vision.colors import ColorPalette  # noqa: E402

WINDOW = "Kalibrasi HSV - AimBot Warna"


def _nothing(_):
    pass


def run(color_key: str, camera_index: int = 0, colors_file=None) -> int:
    colors_file = Path(colors_file or COLORS_FILE)
    palette = ColorPalette.from_json(colors_file)
    spec = palette.by_key(color_key)
    if spec.id == 0:
        print(f"Warna '{color_key}' tidak dikenal. Pilihan: " +
              ", ".join(s.key for s in palette))
        return 1

    lo, hi = spec.hsv_ranges[0] if spec.hsv_ranges else ([0, 100, 100], [179, 255, 255])
    cv2.namedWindow(WINDOW)
    cv2.resizeWindow(WINDOW, 640, 220)
    for name, default in zip(("Low H", "Low S", "Low V", "High H", "High S", "High V"),
                             [*lo, *hi]):
        cv2.createTrackbar(name, WINDOW, int(default), 179 if "H" in name else 255, _nothing)

    cap = cv2.VideoCapture(int(camera_index))
    if not cap.isOpened():
        print(f"Kamera {camera_index} tidak bisa dibuka.")
        cv2.destroyAllWindows()
        return 1
    print("Geser trackbar -> S = simpan, Q = keluar")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.resize(frame, (480, 360))
            hsv = cv2.cvtColor(cv2.GaussianBlur(frame, (5, 5), 0), cv2.COLOR_BGR2HSV)
            vals = [cv2.getTrackbarPos(n, WINDOW)
                    for n in ("Low H", "Low S", "Low V", "High H", "High S", "High V")]
            lower = np.array(vals[:3], np.uint8)
            upper = np.array(vals[3:], np.uint8)
            mask = cv2.inRange(hsv, lower, upper)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)
            preview = cv2.bitwise_and(frame, frame, mask=mask)
            cv2.imshow("Preview", np.hstack([frame, preview]))
            cv2.imshow("MASK", mask)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("s"):
                data = load_json(colors_file, default={})
                for item in data.get("colors", []):
                    if item["key"] == color_key:
                        item["hsv"] = [vals[:3], vals[3:]]
                        if color_key == "merah" and not item.get("hsv2"):
                            item["hsv2"] = [[170, 120, 100], [179, 255, 255]]
                save_json(colors_file, data)
                print(f"Tersimpan: {color_key} = {vals[:3]} .. {vals[3:]}  -> {colors_file}")
    finally:
        cap.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--color-key", default="merah")
    ap.add_argument("--colors", default=None)
    a = ap.parse_args()
    raise SystemExit(run(a.color_key, a.camera, a.colors))
