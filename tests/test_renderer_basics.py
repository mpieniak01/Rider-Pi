import pytest
from PIL import Image

from apps.ui.face.controller import FaceController


@pytest.mark.timeout(4)
def test_basic_frame_renders_and_pupils_visible(monkeypatch):
    # Minimalne środowisko: bez idle, bez driftu, neutral
    monkeypatch.setenv("FACE_IDLE_ENABLE", "0")
    monkeypatch.setenv("FACE_PUPIL_DRIFT_AMP_K", "0.0")

    fc = FaceController(size=200, fps=10, idle=False)
    img = fc.frame_image()  # powinno się wyrenderować bez wyjątków

    assert isinstance(img, Image.Image)
    w, h = img.size
    # Sprawdzenie: dominujący kolor tła ≠ czarny, czyli rysowanie poszło
    r0, g0, b0 = img.getpixel((w // 2, h // 2))
    assert (r0, g0, b0) != (0, 0, 0)

    # Prosty sanity: w obrazie powinny istnieć piksele czarne (źrenice)
    black_count = 0
    for y in range(0, h, max(1, h // 60)):
        for x in range(0, w, max(1, w // 60)):
            r, g, b = img.getpixel((x, y))
            if r < 10 and g < 10 and b < 10:
                black_count += 1
    assert black_count > 0, "Powinny istnieć piksele 'źrenicy' (czarne)"
