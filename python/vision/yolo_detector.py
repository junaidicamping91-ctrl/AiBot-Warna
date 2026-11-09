"""Chapter 1.3 - YOLO Object Detection (OPSIONAL, sesuai poster).

Secara default robot ini cukup memakai deteksi warna. Modul ini menjaga
kesesuaian dengan silabus poster: bila `ultralytics` terpasang, YOLO dipakai
untuk mencari region sasaran, lalu warna diklasifikasikan DI DALAM bounding box
itu. Jika tidak terpasang, modul otomatis fallback ke deteksi warna penuh frame.

Pakai: python python/main.py --detector yolo ...
"""
from __future__ import annotations

import logging

from .color_detector import ColorDetector, Detection
from .colors import ColorPalette

log = logging.getLogger("aimbot")


class YoloColorDetector:
    def __init__(self, color_detector: ColorDetector, palette: ColorPalette,
                 model_name: str = "yolov8n.pt", conf: float = 0.35):
        self.color_detector = color_detector
        self.palette = palette
        self.conf = conf
        self.model = None
        self.reason = ""
        try:
            from ultralytics import YOLO  # type: ignore
            self.model = YOLO(model_name)
        except Exception as exc:  # pragma: no cover - tergantung lingkungan
            self.reason = f"ultralytics tidak tersedia ({exc}); fallback ke full-frame"
            log.warning("YOLO diminta tapi %s", self.reason)

    @property
    def available(self) -> bool:
        return self.model is not None

    def detect(self, frame) -> Detection:
        if not self.available:
            return self.color_detector.detect(frame)

        results = self.model(frame, conf=self.conf, verbose=False)
        boxes = getattr(results[0], "boxes", None)
        if boxes is None or len(boxes) == 0:
            return Detection(frame_size=(frame.shape[1], frame.shape[0]))

        # Ambil box dengan area terbesar
        best, best_area = None, -1.0
        for box in boxes:
            x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
            area = (x2 - x1) * (y2 - y1)
            if area > best_area:
                best, best_area = (x1, y1, x2, y2), area
        x1, y1, x2, y2 = best
        crop = frame[max(0, y1):y2, max(0, x1):x2]
        if crop.size == 0:
            return self.color_detector.detect(frame)

        inner = self.color_detector.detect(crop)
        if not inner.found:
            return Detection(frame_size=(frame.shape[1], frame.shape[0]))
        # Geser koordinat crop kembali ke koordinat frame penuh
        cx, cy = inner.centroid
        bx, by, bw, bh = inner.bbox
        det = Detection(
            color_id=inner.color_id,
            name=inner.name,
            confidence=inner.confidence,
            centroid=(cx + x1, cy + y1),
            bbox=(bx + x1, by + y1, bw, bh),
            area_ratio=inner.area_ratio * (crop.shape[0] * crop.shape[1]) /
                       (frame.shape[0] * frame.shape[1]),
            frame_size=(frame.shape[1], frame.shape[0]),
            mask=inner.mask,
        )
        return det
