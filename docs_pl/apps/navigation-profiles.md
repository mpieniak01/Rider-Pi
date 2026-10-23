# Profile nawigacji i SLOW v1

Rider-Pi jest właścicielem zapisanej selekcji profilu. Oba panele czytają tę samą
konfigurację. Dostępne są `legacy`, `cautious`, `balanced` i `fluid`. Trzy nowe
profile mają status eksperymentalny; wybór profilu nie jest odbiorem jazdy.

## Konfiguracja

GET `/api/navigation/config` dodaje `behavior_catalog` tylko do odpowiedzi:
wersję, wspieraną funkcję, aktywny profil, definicje parametrów i
`effective_policy_sha256`. Skrót obejmuje `behavior` i efektywne parametry
profilu. Niezależnie sprawdzane są rewizja całej konfiguracji, model i źródło.
Katalog nie jest polem zapisywanej konfiguracji.

POST używa istniejącego CAS:

```json
{"revision":0,"values":{"behavior":{"version":1,"profile_id":"balanced","profile_revision":1}}}
```

Brak `behavior` w starszym pliku oznacza Legacy. Nie ma automatycznej migracji
na nowy profil ani swobodnego podawania parametrów z panelu. Definicje obu repo
muszą mieć tę samą wersję i skrót; zmiana wydanych parametrów wymaga nowej
rewizji profilu i ponownej kwalifikacji.

Zmiana wymaga zatrzymania zadań nawigacji/obserwacji oraz aktualnego stanu
wykonawcy: brak ruchu i zerowe wyjście/cel. Odczyt i atomowy zapis są pod wspólnym
mutexem ustawień wykonawcy; STOP go omija. Niezgodna rewizja, ruch lub zajęty
mutex zwracają 409. Zapis zmienia tryb na obserwację, kasuje verified, calibration_id,
model_sha256 i sweep_verified. Nie uruchamia ani nie wyłącza kamery, modeli,
usług lub ruchu i nie przywraca ARM. Ręczna korekta pozostawia automat w pauzie;
wznowienie nadal wymaga trzech nowych poprawnych klatek.

## Capability i wykonanie

Numeracja protokołów decyzji 1/2/3 pozostaje bez zmian. Nowe zachowanie jest
niezależnym rozszerzeniem `temporal_navigation_v1: true` statusu wizji hosta.
Przy nowym profilu preflight sprawdza tę zdolność przed uzyskaniem uprawnienia
ruchu. Starsze pary zachowują Legacy; nieznane SLOW jest odrzucane.

Venom ocenia spójne obszary, ich położenie względem toru oraz historię nowych
klatek. SLOW jest możliwe tylko po kwalifikowanej wolnej drodze, z aktualnym
potwierdzeniem bliskiego toru i ograniczonym współczynnikiem prędkości z profilu.
Pi sprawdza profil/hash, model, rewizję, run/frame/sequence, oryginalny wiek i
pozostały czas. Używa tego samego wykonawcy oraz limitów impulsu/permitu.
Nie zwiększa TTL, okna ARM ani prędkości operatora. Bliska przeszkoda daje ZERO;
wygaśnięty lub zatrzaśnięty przejazd nie odżywa po kolejnym GO.

Skalibrowane kolizje 3D, w tym przeszkody ponad rzutem podłogi, zachowują veto.
Kiepska klatka, zanik źródła, duplikat capture i utrata śledzenia nie tworzą
potwierdzenia przejazdu. Przepięcie profilu/modelu nie odtwarza ruchu.

## Panele i testy

Panel nawigacji Pi pokazuje zapisany profil i draft, parametry tylko do odczytu,
raw prediction, ocenę po stabilizacji, reakcję i przyczynę. Opóźniona odpowiedź
nie nadpisuje nowszej rewizji. Zastosowanie profilu jest osobną akcją; otwarcie
strony, odświeżenie i wybór opcji nie rozpoczynają jazdy.

Ważny permit SLOW oznacza ograniczone pozwolenie, nie potwierdzenie SDK ani
faktyczny ruch. Kolor obrazu i decyzja modelu także nie są uprawnieniem napędu.
Modele semantyczne wybrane jawnie nadal pracują wyłącznie w obserwacji.

Automatyczne testy `tests/test_navigation_behavior.py` i
`tests/operator_navigation_profiles.test.mjs` używają lokalnej izolacji oraz
atrap wyjść. Pełny pytest urządzenia nie jest uruchamiany na fizycznym Pi.
Procedura obserwacji/odbioru ruchu jest osobnym krokiem operatora; profile nie
mają jeszcze potwierdzonej fizycznej płynności ani skuteczności rozpoznawania.

## Wycofanie

Zatrzymaj pętlę, wybierz Legacy i sprawdź nową obserwację. Przy zwykłej zmianie
profilu wcześniejsze uprawnienie jazdy jest usuwane. Przy obniżaniu kodu do wersji
bez obsługi `behavior` zachowaj kopię konfiguracji, a przy postoju i DISARMED usuń
tylko nowe pole, ustaw mode=observe, verified=false, puste calibration_id i
model_sha256 oraz sweep_verified=false. Nie przywracaj starej zgody ruchu z kopii.
Migracja pól tożsamości modelu jest osobna.


[Per-model settings and operator placement / Ustawienia modeli i położenie w panelu](perception-models.md).
