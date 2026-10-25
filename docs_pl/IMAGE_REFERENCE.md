# Referencja pomiarowa obrazu

Referencja na obrazie nawigacji jest pomocą wizualną zapisywaną na Pi,
niezależnie od odbioru jazdy, progów modelu i kalibracji kamery.
purpose=visual_reference_only nie kwalifikuje metrycznej geometrii kolizji.
Zapis nie ustawia postawy, nie porusza robotem, nie uruchamia obserwacji i nie
przyznaje ARM. Referencja najniższej postawy opisuje pomiar operatora,
a nie polecenie przyjęcia tej postawy.

## Trwałość i API

GET /api/navigation/image-reference zwraca version=1, revision, values i purpose.
Przed pierwszym zapisem revision=0, values=null. POST przyjmuje dokładnie
{revision,values}; poprawny zapis atomowy zwiększa rewizję i zwraca zapisany stan.
Nieaktualna rewizja daje 409 image_reference_conflict, błędne dane
422 image_reference_invalid, błąd magazynu 503 image_reference_persistence_failed.
Uszkodzony zapis nie jest cicho zastępowany domyślnym.

Przy negocjowanej kopercie API v1 operacja zapisu potwierdza
configuration_persisted i zapisaną rewizję, actuation=false oraz
physical_completion=not_applicable. Sukces HTTP potwierdza zapis, nie dokładność
pomiaru fizycznego.

Domyślny plik: data/navigation_image_reference.json. RIDER_IMAGE_REFERENCE
wskazuje inną ścieżkę zarządzaną przez operatora. Własna blokada i rewizja
są niezależne od transakcji polityki nawigacji.

## Pola

| Pole | Znaczenie i granice |
| --- | --- |
| visible | Widoczność nakładki, boolean |
| frame_size | Dwie liczby całkowite: szerokość 32–1280, wysokość 32–720 |
| track_width_cm, robot_width_cm, camera_height_cm | Skończone liczby 0.1–1000; robot nie może być szerszy od toru |
| left_edge, right_edge | Po dwa znormalizowane punkty [x,y], wartości 0–1, od wyższego do niższego wiersza obrazu |
| markers | 2–8 par [odległość_cm, znormalizowane_y]; odległości 0.1–1000 rosną, y obrazu maleje |
| reference_pose | Wyłącznie lowest |

Odpowiadające wiersze krawędzi muszą się zgadzać z tolerancją 0.000001;
prawa współrzędna x przewyższa lewą o co najmniej 0.01 w obu wierszach.
Nieznane pola, boolean zamiast liczby, wartości niefinitywne i niepoprawna
kolejność są odrzucane. Definicje: [services/image_reference.py](../services/image_reference.py).

Po konflikcie rewizji odśwież i sprawdź stan przed ponownym zastosowaniem szkicu.
Residual i pewność modelu nie są odległością w cm.
[Wizualizacja nawigacji](NAVIGATION_VISUALIZATION.md) ·
[Kalibracja](apps/calibration.md) · [Parametry polityki](vision-policy-parameters.md).
