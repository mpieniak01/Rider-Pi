"""Optional TFLite detector used by the camera preview."""

from __future__ import annotations

import os

import cv2
import numpy as np


def _detection_outputs(outs):
    boxes = None
    classes = None
    scores = None
    count = None
    for a in outs:
        shp = tuple(a.shape)
        if len(shp) == 3 and shp[2] == 4:
            boxes = a
        elif len(shp) == 2 and shp[1] == 1:
            count = a
    classes, scores = _class_score_outputs(outs)
    return boxes, classes, scores, count


def _preferred_scores(current, candidate):
    if current is None:
        return candidate
    return candidate if candidate.mean() > current.mean() else current


def _class_score_outputs(outs):
    classes, scores = None, None
    for a in outs:
        if a.dtype in (np.float32, np.float16) and len(a.shape) == 2 and a.shape[1] in (10, 25, 100):
            scores = _preferred_scores(scores, a)
        if a.dtype in (np.float32, np.int32, np.int64) and len(a.shape) == 2 and a.shape[1] in (10, 25, 100):
            if classes is None:
                classes = a

    return classes, scores


class TFLiteEffDet:
    def __init__(self, path: str):
        try:
            from tflite_runtime.interpreter import Interpreter
        except Exception:
            from tensorflow.lite.python.interpreter import Interpreter  # type: ignore
        self.interp = Interpreter(model_path=path, num_threads=int(os.getenv("TFLITE_THREADS", "2")))
        self.interp.allocate_tensors()
        self.input_details = self.interp.get_input_details()
        self.output_details = self.interp.get_output_details()
        ishape = self.input_details[0]["shape"]
        self.in_h, self.in_w = int(ishape[1]), int(ishape[2])

    def infer(self, frame_bgr, score_thr: float):
        # Uogólniony parser TF2 Detection API (boxes, classes, scores, count)
        img = cv2.resize(frame_bgr, (self.in_w, self.in_h))
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        inp = np.expand_dims(rgb, 0).astype(np.uint8)
        self.interp.set_tensor(self.input_details[0]["index"], inp)
        self.interp.invoke()

        outs = [self.interp.get_tensor(detail["index"]) for detail in self.output_details]
        boxes, classes, scores, count = _detection_outputs(outs)

        if boxes is None or scores is None or classes is None:
            return []

        boxes = boxes[0]
        scores = scores[0]
        classes = classes[0]
        n = len(scores) if count is None else int(count.flatten()[0])

        H, W = frame_bgr.shape[:2]
        detections: list[tuple[str, float, tuple[int, int, int, int]]] = []
        COCO = {0: "person"}  # minimalny mapping; rozbudujesz wg potrzeb
        for i in range(min(n, len(scores))):
            sc = float(scores[i])
            if sc < score_thr:
                continue
            cls_idx = int(classes[i])
            name = COCO.get(cls_idx, "obj")
            y1, x1, y2, x2 = boxes[i]  # [0..1]
            x1 = int(max(0, min(1, x1)) * W)
            x2 = int(max(0, min(1, x2)) * W)
            y1 = int(max(0, min(1, y1)) * H)
            y2 = int(max(0, min(1, y2)) * H)
            if x2 <= x1 or y2 <= y1:
                continue
            detections.append((name, sc, (x1, y1, x2, y2)))
        return detections
