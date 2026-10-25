# Historyczne demonstracje trajektorii

Producent [apps/demos/trajectory.py](../../apps/demos/trajectory.py) pozostaje
przykładem historycznym. Publikuje surowe type=drive lx/az na starym temacie;
nie buduje aktualnej koperty bezpieczeństwa i nie uzyskuje generacji zadania.
Nie jest zweryfikowanym automatycznym testem fizycznym ani potwierdzoną
autoryzowaną ścieżką przez obecnego wykonawcę.

## Zachowanie i konfiguracja

Sekwencja: przód, obrót w prawo, tył i stara wiadomość stop.
_drive_for publikuje wielokrotnie, a finally próbuje dodatkowej publikacji STOP.
Nie jest to ACK wykonawcy ani dowód zatrzymania fizycznego.

| Zmienna | Domyślnie |
| --- | --- |
| BUS_PUB_ADDR | tcp://127.0.0.1:5555 |
| MOTION_TOPIC | motion |
| DEMO_RATE_HZ | 10 |
| DEMO_SPEED_FWD / DEMO_SPEED_ROT | 0.25 |
| DEMO_SEG_SEC | 2.0 |

To przykładowe polecenia znormalizowane, nie prędkość fizyczna ani kwalifikacja
manewru. MOTION_ENABLE=0 nie izoluje żywego BUS i robota.
Sprawdzenie programowe wymaga jawnie odizolowanego brokera/konsumenta oraz atrap.
Nie uruchamiaj drugiego właściciela UART, aby uzyskać działanie przykładu.

Aktualne sterowanie fizyczne używa [bramy ruchu](motion.md),
[nastaw ręcznych](calibration.md) i osobnej zgody operatora na próbę.
[Symulator](simulator.md) · [katalog zadań](../ZADANIA_USLUGI_ZASOBY.md).
