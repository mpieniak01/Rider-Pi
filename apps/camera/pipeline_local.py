"""Existing local algorithms as a stage of the sole camera producer."""

from __future__ import annotations

import os
from pathlib import Path

VOC_CLASSES = (
    "background aeroplane bicycle bird boat bottle bus car cat chair cow diningtable "
    "dog horse motorbike person pottedplant sheep sofa train tvmonitor"
).split()


def image_transform():
    return {
        "rotation": int(os.getenv("PREVIEW_ROT", "270")),
        "flip_h": os.getenv("PREVIEW_FLIP_H", "0").lower() in {"1", "true", "yes"},
        "flip_v": os.getenv("PREVIEW_FLIP_V", "0").lower() in {"1", "true", "yes"},
    }


def canonical(frame, transform):
    import cv2

    rotation = transform["rotation"]
    if rotation not in {0, 90, 180, 270}:
        raise ValueError("camera_pipeline_rotation_invalid")
    if rotation:
        frame = cv2.rotate(
            frame,
            {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}[rotation],
        )
    if transform["flip_h"]:
        frame = cv2.flip(frame, 1)
    if transform["flip_v"]:
        frame = cv2.flip(frame, 0)
    return frame


class LocalProcessor:
    def __init__(self, engine, *, cv=None, detector=None):
        if cv is None:
            import cv2 as cv
        from apps.vision.config import load_config

        settings = load_config()
        self.cv, self.engine, self.detector = cv, engine, detector
        self.threshold = settings.ssd_preview.ssd_score
        self.edge_low, self.edge_high = settings.edge_preview.edge_low, settings.edge_preview.edge_high
        self.classes = {name.strip().lower() for name in settings.ssd_preview.ssd_classes.split(",")}
        if engine == "ssd" and detector is None:
            root = Path(os.getenv("SSD_MODEL_DIR", "models/ssd"))
            proto, weights = root / "MobileNetSSD_deploy.prototxt", root / "MobileNetSSD_deploy.caffemodel"
            if not proto.is_file() or not weights.is_file() or weights.stat().st_size < 5_000_000:
                raise RuntimeError("camera_pipeline_ssd_model_unavailable")
            self.detector = cv.dnn.readNetFromCaffe(str(proto), str(weights))
        elif engine == "tflite" and detector is None:
            from apps.camera.tflite_detector import TFLiteEffDet

            model = Path(os.getenv("TFLITE_MODEL", "models/efficientdet_lite0.tflite"))
            if not model.is_file():
                raise RuntimeError("camera_pipeline_tflite_model_unavailable")
            self.detector = TFLiteEffDet(str(model))
        elif engine not in {"canny", "ssd", "tflite"}:
            raise ValueError("camera_pipeline_local_engine_invalid")

    def process(self, frame):
        cv, detections = self.cv, []
        if self.engine == "canny":
            gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
            edges = cv.Canny(
                cv.GaussianBlur(gray, (5, 5), 1.0),
                self.edge_low,
                self.edge_high,
            )
            return cv.cvtColor(edges, cv.COLOR_GRAY2BGR), []
        if self.engine == "tflite":
            detections = self.detector.infer(frame, self.threshold)
        else:
            blob = cv.dnn.blobFromImage(
                cv.resize(frame, (300, 300)), 0.007843, (300, 300), 127.5, swapRB=True, crop=False
            )
            self.detector.setInput(blob)
            result = self.detector.forward()
            height, width = frame.shape[:2]
            wanted = self.classes
            allow_all = bool(wanted & {"*", "all"}) or not (wanted - {""})
            for index in range(result.shape[2]):
                confidence = float(result[0, 0, index, 2])
                category = int(result[0, 0, index, 1])
                name = VOC_CLASSES[category] if 0 <= category < len(VOC_CLASSES) else str(category)
                if confidence < self.threshold or not allow_all and name not in wanted:
                    continue
                coords = result[0, 0, index, 3:7]
                x0, y0, x1, y1 = (
                    max(0, min(int(value * limit), limit - 1))
                    for value, limit in zip(coords, (width, height, width, height))
                )
                if x1 > x0 and y1 > y0:
                    detections.append((name, confidence, (x0, y0, x1, y1)))
        output = frame.copy()
        for name, score, (x0, y0, x1, y1) in detections:
            cv.rectangle(output, (x0, y0), (x1, y1), (0, 255, 255), 2)
            cv.putText(
                output, f"{name}:{score:.2f}", (x0, max(0, y0 - 5)), cv.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1
            )
        return output, detections
