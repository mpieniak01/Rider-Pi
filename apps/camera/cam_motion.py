HUMAN_EN   = int(os.getenv("VISION_HUMAN", "0"))  # 1=on, 0=off
FACE_EVERY = int(os.getenv("VISION_FACE_EVERY", "5"))

# w main():
    # ... po start()
    face_cascade = None
    if HUMAN_EN:
        try:
            import cv2
            face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        except Exception:
            face_cascade = None

    fidx = 0
    # w pętli, po policzeniu 'motion':
            human = False
            if HUMAN_EN and face_cascade is not None and (fidx % max(1, FACE_EVERY) == 0):
                # zmniejsz próg i rozmiar detekcji, by było tanio
                faces = face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=3, minSize=(40, 40))
                human = len(faces) > 0
            fidx += 1

            state = {
                "ts": now,
                "motion": motion,
                "moving": motion >= MOTION_THR,
                "human": bool(human),
                "size": [LORES_W, LORES_H],
                "fps": FPS
            }
            pub(pubsock, state)