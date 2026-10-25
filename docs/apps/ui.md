# Local UI and face components

The apps/ui package contains button input, the LCD status UI and the maintained
face package. It is separate from the [web operator panel](../ui/operator-panel.md).

## Current components

- buttons.py publishes ui.button events.
- manager.py, overlay.py, status_panel.py and motion_status.py compose local UI.
- lcd_sink.py and lcd_power.py share display ownership/power handling.
- face/controller.py, animator.py, model.py and renderer.py own face behavior.
- face/face_io.py and panel_cfg.py connect configured rendering to the display.
- Geometry is in apps/draw; hardware access is in drivers/lcd.

The former face_core.py, face_actuators.py and face_emotions.py at the apps/ui
root are not current entry points. Use [face](face.md),
[LCD ownership](face-lcd.md), [drawing](draw.md) and [Face Studio](../FACE_STUDIO.md).

## Button input

| Input | Default GPIO | Setting |
| --- | ---: | --- |
| LEFT | 24 | BTN_LEFT |
| RIGHT | 23 | BTN_RIGHT |
| OK | 17 | BTN_OK |
| BACK | 22 | BTN_BACK |

HOLD_S defaults to 1.0 s. ui.button has id, event=down|up|long and ts.
BUTTONS_SIM=1 selects keyboard input (l/r/Enter/Backspace); GPIO failure also
falls back to simulation. Button events are input, not a motion authorization.
A consumer may act on them, so a keyboard simulation on the production BUS
does not establish test isolation.

Use [actual service mappings](../SYSTEMD_SERVICES_MAPPING.md) and preserve one
LCD owner. The device's mounted display requires its existing 270° compensation.
Tests use fake input, private files and an isolated BUS.
