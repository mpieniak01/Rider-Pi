# Widok nawigacji

Aktualny widok /navigation korzysta ze wspólnego panelu operatora,
istniejącego strumienia SSE /events i GET /api/navigator/status.
Nie potrzebuje dodatkowego demona, portu, WebSocket ani przełącznika ENV.

Pamięć prezentacji API obserwuje robot.pose, mapper.map.data i navigator.path
przez obecny subskrybent BUS. GET tylko odczytuje pamięć; nie żąda mapowania,
nie uruchamia zadania i nie porusza robotem. Zachowuje czas producenta,
a brak danych pozostaje nieznany. Mapa ma limit 65 536 komórek,
plan 2000 punktów. Współrzędne używają dodatniego przesunięcia początku mapy.

Canvas pokazuje przeszkody, wolne/nieznane komórki, pozycję i plan/cel,
jeśli producent je dostarcza. Nie tworzy fikcyjnej pozycji ani trasy.
Wiek i jakość mapy są oddzielone od pozycji/planu. Mapa starsza niż 10 sekund
oraz pozycja/plan starsze niż 3 sekundy są przygaszone.
SSE aktualizuje rzeczywiste dane; polling uzupełnia brak strumienia.

Jawne start/powrót wymagają aktualnej zgody navigation i oryginalnej koperty
generacja/seq/czas. HTTP 202 pozostaje pending. Konfiguracja dostępna jest
wyłącznie w DISARMED. ACK SDK nie potwierdza fizycznego zakończenia.
Przygotuj zgodę na tym samym widoku: jego opuszczenie próbuje STOP
i unieważnia lokalną możliwość ruchu.

Starsza opcjonalna integracja /ws/navigation pozostaje domyślnie wyłączona.
RIDER_NAV_VISUALIZER_ENABLED dotyczy tej osobnej usługi kompatybilności;
nie jest potrzebne do aktualnego panelu.

Pełny kontrakt i weryfikację na loopback opisuje
[panel operatora](ui/operator-panel.md). Test automatyczny nie daje zgody
na ruch fizyczny.
