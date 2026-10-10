# Interfejsy webowe Rider-Pi

Aktualnym interfejsem jest [panel operatora](operator-panel.md).
Dokument opisuje bezpieczeństwo, przygotowanie zadań, właścicieli zasobów,
odświeżanie oraz potwierdzanie żądań.

| Adres | Przeznaczenie |
| --- | --- |
| /view, / | Przegląd: połączenie, bateria, aktualność, zadania i blokady |
| /control | Jeden katalog zadań, jawna zgoda na ruch, żądania i ACK |
| /devices | Kamera, audio, LCD, UART, właściciele i konsumenci; obraz na życzenie |
| /system | Odczyt usług; jawna administracja i osobna zmiana autostartu |
| /navigation | Aktualność mapy/pozycji/planu, żądania nawigacji i konfiguracja w DISARMED |
| /chat | Tekst i opcjonalne TTS; potrzebna domena przygotowywana dopiero przy wysłaniu |

Menu obsługuje język polski i angielski. Język oraz motyw są lokalnymi
preferencjami; nie uruchamiają zadań. Zachowane adresy /home i /google_home
pozostają osobnymi starszymi integracjami.

## Weryfikacja lokalna

Użyj [serwera fixture](operator-panel.md#weryfikacja-bez-robota)
i izolowanych testów. Nie importują API robota, BUS, SDK ani systemd.
Uruchomienie produkcyjnego API nie zastępuje weryfikacji na atrapach.

[Sterowanie](control.md) ·
[Projekcja nawigacji](../NAVIGATION_VISUALIZATION.md) ·
[Dotychczasowa diagnostyka i wersja w stopce](panel-diagnostyka.md)
