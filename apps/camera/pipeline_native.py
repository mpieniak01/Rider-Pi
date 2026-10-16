"""Picamera2 hardware MJPEG adapter; no disk snapshots or local inference."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict


class NativeCamera:
    def __init__(self, publish, *, size=(320, 240), fps=16):
        from picamera2 import Picamera2
        from picamera2.encoders import MJPEGEncoder, Quality
        from picamera2.outputs import Output

        self.camera = Picamera2()
        self.recording = False
        pending, lock, origin = OrderedDict(), threading.Lock(), [None]

        class Encoder(MJPEGEncoder):
            def _encode(self, stream, request):
                stamp = int(request.request.buffers[stream].metadata.timestamp)
                if origin[0] is None:
                    origin[0] = stamp // 1000
                pts = stamp // 1000 - origin[0]
                with lock:
                    now = time.monotonic_ns()
                    if not 0 <= now - stamp <= 1_000_000_000:
                        raise RuntimeError("camera_pipeline_sensor_clock_invalid")
                    pending[pts] = stamp
                    while len(pending) > 32:
                        pending.popitem(last=False)
                super()._encode(stream, request)

        class Sink(Output):
            def outputframe(self, frame, keyframe=True, timestamp=None):
                if not self.recording:
                    return
                with lock:
                    captured = pending.pop(timestamp, None)
                if captured is not None:
                    publish(bytes(frame), captured, size)

        try:
            duration = int(1_000_000 / fps)
            self.camera.configure(
                self.camera.create_video_configuration(
                    main={"size": size, "format": "YUV420"},
                    controls={"FrameDurationLimits": (duration, duration)},
                    buffer_count=4,
                )
            )
            self.camera.start_recording(Encoder(), Sink(), quality=Quality.HIGH)
            self.recording = True
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.camera is None:
            return
        camera, self.camera = self.camera, None
        try:
            if self.recording:
                camera.stop_recording()
        finally:
            camera.close()
            self.recording = False
