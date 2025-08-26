# Rider-Pi — dziennik + cleanup (2025-08-26)

Poniżej masz gotowe, **copy‑friendly** bloki do wklejenia:
- sekcję `PROJECT.md` na dziś,
- uaktualnione `.gitignore`,
- zestaw komend do sprzątnięcia lokala i wypchnięcia zmian.

---

## 1) `PROJECT.md` — wklej/aktualizuj

```markdown
# Rider-Pi — dziennik prac

**Data:** 2025-08-26  
**Kamień:** „baseline usług” — motion+broker jako systemd, rampa + telemetria, menu, E-Stop flagi

## Co zrobione
- **Motion loop**: watchdog, **rampa** (miękki start/stop), **clamp**, deadzone (ENV), **telemetria** `motion.state`.
- **Bezpieczeństwo**: `MOTION_ENABLE` + flaga `data/flags/motion.enable`, **E-Stop** przez `data/flags/estop.on`, opcjonalnie GPIO.
- **Broker**: XSUB↔XPUB (5555↔5556), unit z auto-odblokowaniem portów.
- **Menu (CLI)**: „Demo trajectory (SAFE)”, szybkie drive/stop, E-Stop ON/OFF, status.
- **Narzędzia**: `scripts/pub.py`, `scripts/sub_dump.py`, `scripts/sub_state.py`, `scripts/estop.py`.
- **systemd**: `rider-broker.service`, `rider-motion.service`, (opcjonalnie) `rider-menu.service`.

## Jak uruchamia się po reboocie
- `rider-broker.service` — aktywny
- `rider-motion.service` — aktywny (domyślnie symulacja, dopóki nie ma flagi/ENV)
- (opcjonalnie) `rider-menu.service`

## Szybka procedura testowa (po reboocie)
1. Health:
   - `sudo systemctl status rider-broker.service rider-motion.service`
2. Telemetria:
   - `python3 -u scripts/sub_state.py` → ramki ~5 Hz
3. Demo (symulacja):
   - `python3 -u apps/demos/trajectory.py`
   - w logu motion: `[SIM] move …` + pojedynczy `MOTION: STOP`
4. Watchdog:
   - `python3 -u scripts/pub.py motion '{"type":"drive","lx":0.3,"az":0.0}'` → po ~0.5 s STOP
5. E-Stop:
   - `python3 -u scripts/estop.py on` / `off`
6. **Fizyczny ruch (ostrożnie, kiedy gotowi)**:
   - `touch data/flags/motion.enable` → demo jak wyżej → `rm data/flags/motion.enable`

## Następne kroki
- Uzupełnić `apps/motion/xgo_adapter.py` pod realny sterownik i test fizyczny.
- (Opc.) pin **ESTOP_GPIO**, twarde limity `MOTION_MAX_LX/AZ`, dopracować README (runbook).

## Szybki troubleshooting
- Broker pada: zwykle port 5555/5556 zajęty → `sudo fuser -k 5555/tcp 5556/tcp` + restart usługi.
- Motion nie reaguje: sprawdź topic w `scripts/sub_dump.py`; czy jest `motion {...}`.
- Spam STOP: upewnij się, że jedna instancja (`pgrep -fl apps/motion/main.py`) oraz rampa/anty-spam w kodzie.
```