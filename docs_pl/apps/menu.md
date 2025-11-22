# Moduł Menu (`apps/menu`)

## Opis

Moduł `apps/menu` implementuje **menu nawigacyjne** dla robota — podobny do `apps/launcher`, ale potencjalnie z dodatkowymi funkcjami.

⚠️ **Uwaga:** Plik `apps/menu/main.py` ma identyczną zawartość jak `apps/launcher/main.py`. Prawdopodobnie jeden z nich jest przestarzały lub duplikatem.

### Główny plik

- **`main.py`** — menu na 4 przyciski (identyczne z launcher)

## Relacja do launcher

Według analizy kodu:
- `apps/menu/main.py` = `apps/launcher/main.py` (identyczna funkcjonalność)
- Oba moduły subskrybują `ui.button` i `motion.state`
- Oba publikują `system.mode`, `motion.cmd`, `system.menu.state`

**Rekomendacja:** Użyj **`apps/launcher`** jako głównego modułu menu. Moduł `apps/menu` może być przestarzały.

## Zobacz dokumentację

Pełna dokumentacja funkcjonalności menu znajduje się w:
- [**launcher.md**](launcher.md) — moduł menu startowego

## Różnice (jeśli istnieją)

⚠️ **Wymaga weryfikacji:**
- Sprawdź historię commitów Git dla `apps/menu/` i `apps/launcher/`
- Możliwe że jeden jest refaktoryzacją drugiego
- Lub jeden służy do testów/dev, drugi do produkcji

## Przykład użycia

```bash
# Uruchom menu (identycznie jak launcher)
python -m apps.menu.main
```

## Rekomendacje

1. **Jeśli oba są identyczne:** Usuń jeden z nich i zaktualizuj referencje
2. **Jeśli służą różnym celom:** Dodaj komentarz w kodzie wyjaśniający różnice
3. **Dla nowych użytkowników:** Używaj `apps/launcher` (nowszy?)

---

**Related docs:**
- [launcher.md](launcher.md) — pełna dokumentacja menu startowego
- [ui.md](ui.md) — moduł UI (przyciski)

**Ostatnia aktualizacja:** 2025-01  
**Status:** ⚠️ Możliwy duplikat `apps/launcher` — wymaga weryfikacji
