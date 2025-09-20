# Ustalenia robocze

---

## Gałęzie i PR-y

- **main** = stabilny, testy zielone.
- Nowa praca: `git switch -c feat/<temat>` (lub `fix/…`, `chore/…`).
- Push: `git push -u origin feat/<temat>` i otwórz PR do `main`.

---

## Środowisko dev (lokalnie)

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
# lekkie test deps (fallback gdy brak pliku)
pip install -r ops/agent/requirements-test.txt || \
  pip install pytest==8.4.2 pytest-timeout==2.4.0
```

---

## Pre-commit (Ruff)

Repo zawiera `.pre-commit-config.yaml`. Zainstaluj raz:

```bash
pip install pre-commit
pre-commit install
```

Ręcznie (całe repo):

```bash
pre-commit run --all-files
```

> Legacy i deprecated są wykluczone w hookach (ścieżki: `attic/`, `_apps/`, `services/_deprecated_*`).

---

## Lint i format

- Lint: `ruff check .`
- Format: `ruff format .`
- Target: **Python 3.9** (ustawione w `pyproject.toml`).
- Dla wyjątków importów w skryptach CLI używamy `# noqa: E402` tylko tam, gdzie to potrzebne.

---

## Testy

Szybko lokalnie:

```bash
pytest -q
# pojedynczy test:
pytest -q tests/test_face_lcd_anim.py::test_render_and_legacy
```

W CI testy lecą „lite” (bez HW), z env:
```
RIDER_NO_HW=1
FACE_SINK=png
RIDER_APPS_PATH=_apps:apps
```

---

## Styl commitów (lekko)

- Prefiksy: `feat:`, `fix:`, `chore:`, `test:`, `docs:`
- Przykład: `chore(pre-commit): exclude legacy from hooks`

---

## Checklist PR (skrót)

- [ ] `pre-commit run --all-files` zielone
- [ ] `pytest -q` przechodzi lokalnie
- [ ] Zmiany nie dotykają `attic/legacy` (chyba że to świadomy cleanup)
- [ ] Opis PR: zakres, wpływ na testy/CI, ew. migracje

---

## CI (GitHub Actions)

- `.github/workflows/ci.yml` — szybkie testy (py3.9, bez HW).
- `.github/workflows/tests-audit.yml` — audyt testów (opcjonalny).
- Jeśli CI czerwone — odpal te same kroki lokalnie i porównaj logi.

---

## FAQ

**Q:** „Pre-commit krzyczy na legacy.”  
**A:** Hooki mają `exclude` (oraz Ruff ma `extend-exclude`); jeśli coś „przecieknie”, sprawdź ścieżkę i dopisz wykluczenie.

**Q:** „Różnice po merge’ach/PR-ach?”  
**A:** Upewnij się, że jesteś na `main` i zaktualizowany:

```bash
git fetch --all --prune
git switch main
git pull --ff-only
```

---

# Pull Request Template

Poniżej szablon PR — wklej go do opisu PR na GitHubie.

---

## Co zmienia ten PR?
<!-- krótko: co, dlaczego, efekt -->

## Zakres
- [ ] Kod
- [ ] Testy
- [ ] Dokumentacja / komentarze
- [ ] CI / pre-commit

## Jak testować?
<!-- komendy, kroki, co powinno wyjść -->

## Wpływ
- [ ] Brak wpływu na legacy (attic/_apps/_deprecated)
- [ ] Wymagana migracja / zmiany w środowisku (opisz poniżej)

## Checklist
- [ ] `pre-commit run --all-files` zielone
- [ ] `pytest -q` przechodzi lokalnie
- [ ] PR do `main`, opis zawiera kontekst