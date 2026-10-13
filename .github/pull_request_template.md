## Zakres
Krótko: co PR przenosi/porządkuje (MOVE-FIRST), bez zmiany zachowań.

## Checklista (WYMAGANE)
- [ ] **MOVE-FIRST** (w diff widoczne renames/moves).
- [ ] **NO-STUB**: nie zastąpiłem działającej logiki szkieletem (`pass`/`TODO`/`NotImplementedError`).
- [ ] Brak nieuzasadnionych delecji. Jeśli są: label **allow-delete** + DLACZEGO.
- [ ] Publiczne importy/API kompatybilne (re-eksporty zapewnione).
- [ ] `ruff check --fix && ruff format` zielone (≤120 znaków/linia).
- [ ] `pytest` zielony (dla audio: `ALSA_SKIP_LSOF=1 pytest -q -k voice`).
- [ ] Zmienione pliki Python mają maksymalnie **800 linii**; ostrzeżenia **601–800** oceniono pod kątem spójności odpowiedzialności.

## Uwagi techniczne (opcjonalnie)
Co przeniesiono i gdzie, ewentualne decyzje projektowe.
