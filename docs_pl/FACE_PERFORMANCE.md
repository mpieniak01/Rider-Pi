# Pomiar buźki na Rider-Pi

Pomiar na oryginalnym XGO-Rider CM4 (Python 3.9, Pillow 9.5.0), 2026-10-12.
Baza: `354cfddccb7602de4e642d0f454af8f6821364ef`. Implementacja sprawdzona
na lokalnym podglądzie `5756357fd3c0670f4d414a20900e40afdaef2da6`.

## Pomiar renderowania

`scripts/face_benchmark.py` rysuje dynamiczne klatki 240×240 i konwertuje
każdą do RGB565. Każdy wariant działa w osobnym procesie: 20 klatek rozgrzewki,
300 mierzonych klatek, następnie trzy sekundy z ograniczeniem do 12 FPS.
CPU to czas procesora podzielony przez czas rzeczywisty; 100% oznacza jeden rdzeń.

| Wariant | Średnia | p95 | CPU przy 12 FPS | Szczytowe RSS procesu | Wzrost RSS w pętli |
| --- | ---: | ---: | ---: | ---: | ---: |
| Przyjazna | 4,727 ms | 5,360 ms | 6,01% | 34,99 MiB | 2,11 MiB |
| Prosta | 4,763 ms | 5,470 ms | 5,70% | 35,27 MiB | 2,07 MiB |
| Poprzedni renderer | 12,037 ms | 12,647 ms | 14,74% | 35,36 MiB | 1,41 MiB |

Nowy komponent spełnia początkowy cel renderowania: średnia ≤5 ms, p95 ≤10 ms.
Podczas pomiaru zakodował **zero PNG**. Szczytowe RSS jest porównywalne
z poprzednim komponentem. Krótki pomiar nie potwierdza stabilności pamięci
w długim czasie; ograniczenia cache i kanałów obejmują też testy celowe.

Są to **wyniki komponentu renderującego** bez SPI, zapytań API, podglądu WWW
i innych usług robota. Nie oznaczają całkowitego CPU API, poboru energii
ani czasu pracy baterii.

Powtórzenie na Pi bez otwierania LCD i UART:

```sh
python3 scripts/face_benchmark.py --style friendly
python3 scripts/face_benchmark.py --style minimal
python3 scripts/face_benchmark.py --baseline-ref 354cfddccb7602de4e642d0f454af8f6821364ef
```

## Obserwacje urządzenia i przeglądarki

- Operator potwierdził widoczną i poprawną radosną buźkę na LCD.
  Zachowano dotychczasową orientację 270°.
- Przy wyłączonych naturalnych gestach licznik klatek pozostawał równy
  cztery w kolejnych odczytach: nieruchomy obraz nie był stale wysyłany na SPI.
- Próba w trybie baterii zakończyła się po około 45 sekundach; sterownik
  potwierdził przyjęcie wyłączenia podświetlenia. Późniejszą próbę w trybie
  kabla zatrzymano na polecenie operatora: wykonawca buźki zakończył pracę
  i zgłosił wyłączony LCD. Przywrócono tryb baterii i naturalne gesty.
- Ostatnia prezentacja zmienionej klatki w próbie na kablu zajęła 67,56 ms.
  To pojedyncza obserwacja, **nie** średnia/p95 SPI. Obejmuje również
  przygotowanie płótna i raportowanie stanu urządzenia.
- Poprawiono przypadek cienkich zaokrągleń w Pillow 9.5 na CM4 oraz wspólny
  uchwyt SPI biblioteki producenta. Ponowne otwarcie ma test własności zasobu;
  kolejnego fizycznego cyklu stop/start po tej poprawce nie wykonywano po
  poleceniu operatora, aby wyłączyć ekran.
- Sprawdzono w przeglądarce rzeczywisty adres Studio na Pi, układ desktop/mobile,
  wspólne ustawienia, klatki szkicu, klatki wykonawcy i obsługę nieaktywnego
  podglądu. Źródło aktywne pokazuje wyłącznie wykonawcę buźki.
- Wykonano powrót podglądu do czystej bazy i ponowne wdrożenie.
  Wykonawca ruchu nie był restartowany; nie wysyłano poleceń ruchu.

## Weryfikacja programowa

Końcowa regresja lokalna: **1817 testów Python zaliczonych**, 40 pominiętych,
8 podtestów zaliczonych; **141 testów JavaScript zaliczonych**; Ruff i kontrola
diff zakończone poprawnie. Testy bez sprzętu obejmują zastępowanie/prioritet
animacji, watchdog audio, cache obrazu, limity katalogu, zapis atomowy,
konflikt rewizji, własność LCD, orientację i zamknięcie oraz usuwanie zapytań
i timerów w ukrytej karcie.

Współpraca z kamerą/głosem na fizycznym sprzęcie, długi pomiar CPU/RAM,
reprezentatywne czasy SPI i zużycie energii pozostają dalszymi pomiarami.
Nie deklarujemy zmierzonej oszczędności baterii ani integracji z dostawcą mowy.
