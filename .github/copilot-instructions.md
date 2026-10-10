# Copilot PR Instructions — Rider-Pi

## Cel
Recenzuj PR-y tak, by **nie tracić funkcjonalności**. Egzekwuj:
- **MOVE-FIRST** (git mv → przenoszenie realnego kodu),
- **NO-STUB** (zakaz pustych szkieletów: `pass`, `raise NotImplementedError`, `TODO`),
- **NO-DELETE** bez etykiety `allow-delete` + uzasadnienia,
- **zgodność z ruff** (≤120 znaków/linia) i testami.

## Na co patrzeć
- Czy renames/moves przeważają nad delete?
- Czy nie zniknęły publiczne klasy/metody (np. `StreamingVoiceService`, itp.)?
- Czy nowe moduły mają realną implementację (nie szkielety)?
- Czy importy/re-eksporty zachowują kompatybilność API?
- Czy logika (ASR→CHAT→TTS, PTT, zamykanie WS) nie uległa „po cichu” zmianie?

## Wymagaj w PR
- Krótki opis: *co przeniesiono i gdzie* (bez powielania zasad z AGENT.md).
- Zielone: `ruff check --fix && ruff format` oraz `pytest` (dla audio: `ALSA_SKIP_LSOF=1 pytest -q -k voice`).

## Dokumentacja i materiały lokalne

Stosuj [politykę dokumentacji](../docs_pl/POLITYKA_DOKUMENTACJI.md). Plany w `docs_pl/_to_do/` i raporty
w `docs_pl/_done/` są lokalne, ignorowane i nie trafiają do commitów
ani załączników PR. Utrzymywane instrukcje i używane przez nie assety
publikujemy w `docs/` i `docs_pl/`. Nie stosuj `git add -f` dla materiałów
lokalnych. Przy usuwaniu ich z indeksu Git zachowuj kopie na dysku.

Wersja polska jest punktem wyjścia. Aktualizuj także wersję angielską
kontraktów i instrukcji; katalogi operacyjne utrzymuj wyłącznie w `docs_pl/`.
