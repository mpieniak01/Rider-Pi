# Etap 2 – Wydzielenie modułów przetwarzania

## Podsumowanie wykonanych zmian
- **Frame distributor** – dodano usługę `frame-distributor.service` oraz moduł `apps.camera.frame_distributor`, który nasłuchuje na `camera.heartbeat`, odczytuje najświeższy plik `last_frame.*` i publikuje klatki w formie strumienia ZMQ (`camera.frame.raw`). Dzięki temu wszystkie moduły ML mogą subskrybować wspólny kanał zamiast sięgać po `/dev/video`.
- **Integracja z App Logic** – `FeatureManager` przy włączaniu funkcji wymagających podglądu startuje zarówno `camera-capture@raw.service`, jak i `frame-distributor.service`, a przy wyłączaniu sprząta oba unity. Scenariusz S2 zawiera teraz obie usługi, więc UI ma pewność, że feed jest dostępny.
- **Tracker MediaPipe, obstacle ROI i offload** – `apps/vision/tracker_mediapipe.py`, `apps/vision/obstacle_roi.py` oraz `apps/vision/offload_dispatcher.py` korzystają domyślnie z nowego strumienia (`camera.frame.raw`), a dopiero w razie braku danych wracają do plików lub kamery. Dzięki temu każdy moduł (w tym wysyłka klatek do PC) bazuje na tym samym feedzie.
- **Topic’i wynikowe** – tracker publikuje `tracking.pose`, obstacle ROI emituje `obstacle.map`, a mapper udostępnia telemetrię `slam.map` (statystyki mapy + aktualna pozycja). Dzięki temu kolejne moduły (mapper, navigator) mają spójne źródła danych w busie.

## Wnioski
Warstwa processing ma już dedykowany komponent dystrybucji klatek, a pierwszy moduł (tracker) konsumuje go wprost. Zasady „jedna kamera → wielu konsumentów” są respektowane – App Logic nie pozwoli na start scenariusza bez wspólnego feedu.

## Następny krok
- Dostosować pozostałe moduły (`rider-mapper`, `rider-vision-offload`) do korzystania z `frame-distributor` i spisać kontrakt topiców wynikowych (`tracking.pose`, `obstacle.map`, `slam.map`). Wtedy wszystkie scenariusze będą dzielić feed bez ręcznej konfiguracji.***
