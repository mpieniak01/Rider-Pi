# Lokalny interfejs i komponenty buźki

Pakiet apps/ui zawiera przyciski, lokalny status LCD i aktualny pakiet buźki.
To osobny interfejs od [panelu webowego](../ui/operator-panel.md).

## Aktualne komponenty

- buttons.py publikuje ui.button.
- manager.py, overlay.py, status_panel.py i motion_status.py składają lokalny UI.
- lcd_sink.py i lcd_power.py współdzielą własność i zasilanie ekranu.
- face/controller.py, animator.py, model.py i renderer.py realizują buźkę.
- face/face_io.py i panel_cfg.py łączą rendering z ekranem.
- Geometria jest w apps/draw, dostęp do sprzętu w drivers/lcd.

Dawne face_core.py, face_actuators.py i face_emotions.py w korzeniu apps/ui
nie są aktualnymi punktami wejścia. Zobacz [buźkę](face.md),
[własność LCD](face-lcd.md), [rysowanie](draw.md) i [Studio buźki](../FACE_STUDIO.md).

## Przyciski

| Wejście | Domyślne GPIO | Ustawienie |
| --- | ---: | --- |
| LEFT | 24 | BTN_LEFT |
| RIGHT | 23 | BTN_RIGHT |
| OK | 17 | BTN_OK |
| BACK | 22 | BTN_BACK |

HOLD_S domyślnie 1.0 s. ui.button zawiera id, event=down|up|long i ts.
BUTTONS_SIM=1 wybiera klawiaturę (l/r/Enter/Backspace); błąd GPIO także przechodzi
do symulacji. Zdarzenie wejściowe nie jest zgodą ruchu. Konsument może jednak
zareagować, więc klawiatura na produkcyjnym BUS nie potwierdza izolacji testu.

Stosuj [rzeczywiste mapowanie usług](../SYSTEMD_SERVICES_MAPPING.md) i jednego
właściciela LCD. Zachowuj kompensację montażu 270°.
Testy używają atrap wejścia, prywatnych plików i odizolowanego BUS.
