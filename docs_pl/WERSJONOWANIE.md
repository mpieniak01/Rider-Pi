# Wersjonowanie i wydania

## Numer projektu

Plik [VERSION](../VERSION) zawiera wersję projektu w formacie `MAJOR.MINOR.PATCH`.
Wydanie 1.0 używa `1.0.0`, tagu `v1.0.0` i opisów w obu językach:
[PL](release-notes/v1.0.0.md), [EN](../docs/release-notes/v1.0.0.md).
README PL/EN podają tę samą wersję. Przy następnym wydaniu zmień VERSION,
oba README i oba opisy wydania w jednym PR.

- PATCH: zgodne poprawki błędów i dokumentacji.
- MINOR: nowe funkcje zachowujące publiczne kontrakty.
- MAJOR: zmiany wymagające migracji istniejących klientów lub konfiguracji.

Numer projektu jest osobny od SDK producenta, firmware oraz numerów kontraktów
HTTP/BUS. `/api/status/version` nadal pokazuje gałąź, SHA i czystość checkoutu;
nie jest źródłem wersji semantycznej. Historyczne tagi, w tym `R-1.1.7`,
pozostają niezmienione. Linia `v1.0.0` wprowadza wspólną konwencję dla kolejnych wydań.

## Przygotowanie wydania

1. Otwórz PR z aktualizacją VERSION, README PL/EN i opisów wydania. Zachowaj
   Python 3.9 oraz zakres zmian opisany w [development](development.md).
2. Sprawdź wyniki dla aktualnego SHA: Tests, Quality Guard, Sonar i dostępne
   kontrole zewnętrzne. Rozpatrz rzeczywiste uwagi recenzji. Wymagane warunki
   wynikają z ochrony gałęzi; brak opcjonalnej recenzji nie jest wynikiem błędu.
3. Scal PR bez omijania ochrony, wyrównaj czysty lokalny `main` fast-forward
   i sprawdź workflow push dla SHA integracji. Poczekaj na raport Sonara
   dla tej samej rewizji. Nie uruchamiaj równoległego lokalnego skanera.
4. Utwórz adnotowany tag na sprawdzonym SHA i opublikuj tylko ten tag:

```sh
git switch main
git pull --ff-only origin main
# Kontrole i raport main muszą już odpowiadać temu SHA.
version=$(cat VERSION)
sha=$(git rev-parse HEAD)
git tag -a "v$version" "$sha" -m "Rider-Pi $version"
git push origin "refs/tags/v$version"
```

5. W GitHub Releases wybierz istniejący tag, tytuł `Rider-Pi <wersja>` i opis
   z `docs/release-notes/`. Opublikuj jako zwykłe wydanie, gdy kontrole są
   zakończone. Archiwa źródeł GitHub nie zawierają ignorowanych sekretów i raportów.

Nie przesuwaj opublikowanego tagu ani nie stosuj force push. Korekta wydania
otrzymuje następny numer i nowy tag. Nowy tag ani plik VERSION nie zmieniają
konfiguracji lub bazy nowego kodu Sonara. Publikacja wydania GitHub nie jest
wdrożeniem na robota; [wdrożenie](WDROZENIE.md) jest osobnym krokiem.
