# Tor kamery v1 — Rider-Pi i Venom

Pi przechowuje profil i jego rewizję oraz zarządza kamerą. Venom wykonuje zdalną
inferencję. Ten sam profil jest widoczny w obu panelach; przeglądarka nie zapisuje
drugiej konfiguracji. Pełny protokół opisuje [wersja angielska](../docs/CAMERA_PIPELINE_V1.md),
a schemat i syntetyczne przykłady są w config/contracts/camera_pipeline_v1.*.

## Obsługa

W panelu /view lub /control, a także w kamerze panelu Rider w Venom, wybierz:

- Analiza obrazu: lokalnie na Pi albo w Venom.
- Lokalnie: dostępny silnik Canny, SSD lub TFLite. Lista wynika z bibliotek i modeli
  faktycznie zainstalowanych na Pi. Nie pobiera ich ani nie ładuje przy odczycie.
- W Venom: klatki JPEG albo natywny MJPEG.
- Kamera ON/OFF: jawny start lub zatrzymanie kamery. Wejście na stronę jest odczytem.

Nieaktywny wybór transportu/silnika pozostaje zapamiętany do następnego przełączenia.
Zmiana profilu zatrzymuje stary tor, potwierdza zwolnienie kamery i zapisuje nową
rewizję. Przy aktywnym podglądzie wraca jedynie pasywna kamera S2. Nie wznawia jazdy,
analizy S14/S15 ani uzbrojenia. Konflikt z innym właścicielem jest pokazywany operatorowi.
Stary producent bez zapisanego profilu jest oznaczony compatibility_mode=legacy;
jawne configure/start przeprowadza go na nowy tor.

Analiza lokalna nie jest automatyczną zgodą na jazdę. Zachowane są trzy znaczenia
STOP: zero silników, zakończenie pętli z kamerą, globalny STOP/rozbrojenie.
Sterowanie ręczne pozostaje niezależne od modelu AI.

## Przepływ obrazu

Jeden proces posiada kamerę. Lokalne filtry pracują na jego surowym buforze RAM.
MJPEG korzysta z enkodera kamery i ograniczonego IPC w /run/rider-camera.
Nie zapisuje cyklicznych JPEG na karcie SD i nie uruchamia starego dystrybutora.
Obraz PROC jest kodowany dopiero dla jawnego odbiorcy. Tracker korzysta z tego
samego źródła i odrzuca stare lub powtórzone dane zamiast czytać dawny plik.

Venom utrzymuje wspólny odbiornik dla podglądu i analizy. Żądanie decyzji natywnego
toru podaje referencję istniejącej klatki; nie wysyła drugi raz JPEG.
Obrót zgodny z ruchem wskazówek zegara, a następnie odbicia, są przenoszone jako
image_transform i stosowane raz przed analizą/wyświetleniem. Pi nie koduje JPEG
ponownie tylko dla obrotu. Lokalne filtry i oba panele zachowują ten sam układ stron.

Przeglądarka używa odczytu MJPEG albo okresowych klatek, a nie obu jednocześnie.
Wolny odbiorca pomija klatki pośrednie. Każda klatka ma sesję, sekwencję, epokę
transportu, rewizję profilu, hash oryginalnych bajtów i czas przechwycenia.

Wiek pochodzi z monotonicznego zegara Pi. Venom i panel dodają własny czas od
odbioru; żaden host nie odejmuje zegara drugiej maszyny. Cache, reconnect, zapis
pliku lub odrysowanie zielonej maski nie odnawiają wieku. Zatrzymany obraz pozostaje
jawnie stary. Limit podglądu jest odrębny od niezmienionego limitu decyzji ruchu.

Przygotowanie odbiornika Venom odbywa się przed przekazaniem sterowania istniejącej
próbie. Pi sprawdza zgodność sesji/epoki/rewizji oraz pełny czas od przechwycenia do
powrotu odpowiedzi. Brak łączności nie włącza lokalnego zastępstwa ani starego GO.

## API i trwałość

| Miejsce | Interfejs |
| --- | --- |
| Pi | GET/POST /api/resource/camera/pipeline |
| Pi | GET /api/resource/camera/stream.mjpg |
| Pi | GET /api/resource/camera/frame?view=raw lub proc |
| Venom | GET/POST /api/v1/rider/camera/pipeline |
| Venom | GET /api/v1/rider/camera/stream/raw lub venom |
| Venom | POST /api/v1/rider/compute/vision/decision-reference |
| Przygotowanie | GET /api/v1/rider/compute/vision/status?stream=true |

Zmiana zawiera contract_version=1, request_id, expected_revision i action.
Configure wymaga całego profilu; start/stop zabrania pola profile. Powtórzone
identyczne żądanie jest idempotentne; konflikt rewizji lub aktywności daje 409.
Niepoprawny format daje 400, niedostępny runtime 503.

Profil: data/camera_pipeline.json, zmiana ścieżki RIDER_CAMERA_PIPELINE_CONFIG.
Stan i IPC: /run/rider-camera, zmiana RIDER_CAMERA_PIPELINE_RUNTIME.
Brak pliku zachowuje zgodny domyślny venom/snapshots/canny i niczego nie uruchamia.
Starszy Pi jest rozpoznawany jako unsupported, bez udawania nowego kontraktu.

Nowe API korzysta z obecnej granicy zaufania zasobów/kamery. Token wykonawcy ruchu
nie trafia do adresów mediów. Proxy Venom zachowuje sesję urządzenia, a endpointy
decyzji dotychczasowe uwierzytelnienie compute.

## Wdrożenie i odbiór

Podgląd: make pi-preview PI_DEPLOY_ARGS='--restart-api --vision-loop-scope'.
Zakres vision-loop-scope dopuszcza tylko wymienione unity wizji i jednostkę kamery
z katalogiem RuntimeDirectory; nie włącza autonomii. Po zmianie jednostki wykonaj
daemon-reload i sprawdź jej faktyczny FragmentPath. Nie używaj zbiorczego
systemd-sync ani restartu wykonawcy ruchu do aktualizacji kamery.

Testy automatyczne używają fixture i IPC bez sprzętu. Odbiór kamery na Pi jest
osobnym sprawdzeniem bez ARM i ruchu. Zielony overlay, ACK enkodera i test mocka
nie są dowodem fizycznej jazdy. Poprzednia rewizja pozostaje dostępna przez
make pi-rollback; po powrocie trzeba też przeładować zmienioną jednostkę.

## Wydanie i powrót do klatek

Zmiany tworzą parę: Rider-Pi #280 oraz venom-module-rider #18. Rdzeń Venom korzysta
z obecnego interfejsu modułów i nie wymaga zmiany kodu. Domyślne ustawienia nowej
instalacji nadal używają klatek i DA2; MJPEG jest opcją wymagającą osobnego odbioru.
Brak plików modeli SSD/TFLite jest pokazywany w capabilities, bez podstawiania
innego silnika.

Przygotowanie MJPEG najpierw czeka na świeżą klatkę RAM bieżącej sesji i rewizji,
a następnie sprawdza gotowość odbiorcy Venom. Zimny producent zwraca ready=false;
rzeczywista awaria pozostaje błędem. Odbiór odpowiedzi nie odnawia wieku źródła.
Do wycofania transportu zatrzymaj pętlę i kamerę, wybierz Venom + Klatki w jednym
z paneli i uruchom obserwację. Sam zapis profilu nigdy nie wznawia jazdy.

Picamera2 używa czasu przechwycenia sensora. Backend OpenCV zgłasza ograniczenie:
czas początku odczytu nie dowodzi wieku obrazu w buforze sterownika. Klient
wiąże źródło z odczytem stanu Pi i dolicza cały czas zapytania; nie odejmuje
zegarów różnych urządzeń.

Identyfikatory żądania pętli (VisionFrame.frame_id/sequence) nie są identyfikatorami
sensora. Źródło kamery ma własne source.frame_id/sequence i sześciopolową referencję.
Podgląd porównuje wszystkie pola referencji z obrazem; odpowiedź do Pi zachowuje
licznik i identyfikator żądania. Spóźniona klatka w obserwacji daje UNKNOWN/STOP
i jest odrzucana; następna ocena wymaga nowego źródła. Jazda zachowuje STOP.

## Zgodność orientacji RAW

Brak lub pusta wartość PREVIEW_ROT oznacza 0°, tak jak w dotychczasowym RAW. Jawne ustawienia obrotu i odbić pozostają zachowane. Kompensacja montażu LCD jest oddzielnym ustawieniem i nie wyznacza orientacji obrazu kamery. Snapshot koduje obraz po transformacji; MJPEG przenosi transformację do odbiorcy, który stosuje ją dokładnie raz.

## Czas decyzji referencyjnej a granica podglądu

Dla uwierzytelnionego żądania Pi czas do decyzji wynika z wieku zgłoszonego na zegarze Pi i czasu obsługi na Venom. Uwzględniany jest również minimalny wiek części: zapisany wiek w chwili wysłania i czas w buforze hosta. Górna granica z kotwicy statusu zawiera niepewność całego RTT i pozostaje granicą podglądu/cache; nie jest dokładnym wiekiem do sterowania. Pi nadal egzekwuje pierwotny deadline 300 ms od captured_monotonic_ns, także tuż przed wysłaniem polecenia silnikom. Host GO nie odnawia tej granicy.

Opcjonalne source_timing_ms pokazuje pi_reported_age, host_before_inference, observed_age, upper_age i deadline_age. Dane służą diagnostyce i nie udzielają zgody na ruch.

## Podgląd operatora i historia pomiarów

W przetworzonym podglądzie Venom L (turkusowy), C (biała granica STOP) i R
(fioletowy) oznaczają strefy użyte w analizie widocznej klatki. W trybie obrazu
odpowiadają rzeczywistej strefie i sąsiednim obszarom, a nie trzem równym częściom
całego obrazu. Tryb geometrii podłoża pokazuje rzuty torów. Niepełna lub niedostępna
geometria ma ocenę niepewną. Pomarańczowa przerywana ramka edytora jest niezapisanym
szkicem; jej przesunięcie nie zmienia ocen przypisanych wcześniej do obrazu.

Widoczny JPEG i metadane źródła pozostają parą do załadowania następnego obrazu.
Tekstowe karty pokazują najnowszą zdekodowaną ocenę L/C/R co sekundę, aby ułatwić
odczyt; mogą więc chwilowo pozostawać za obrazem na żywo. Próbka zachowuje własną
identyfikację klatki. Obraz i faktyczna decyzja ruchu zachowują normalną częstotliwość.
Nieprawidłowe dane źródła albo zmiana kamery, modelu lub polityki od razu unieważniają
poprzednią próbkę. Zasada dotyczy klatek i MJPEG. Obraz zachowuje pierwotny termin
ważności, a alert nieświeżych danych pozostaje widoczny. Karty nie udzielają zgody
na ruch. Pasek operatora z ARM i globalnym STOP pozostaje widoczny przy przewijaniu.

Przegląd Pi zachowuje historię CPU/RAM z oryginalnymi znacznikami czasu po błędzie
odczytu i pokazuje błąd oraz wiek pomiaru. Okno przesuwa się przez ostatnie 60 sekund
na osi czasu Pi, także podczas awarii. Stare punkty wygasają, a przerwy pozostają
widoczne; panel nie rozciąga indeksów próbek, nie wpisuje pomiarów zerowych ani nie
odmładza zatrzymanej serii.
