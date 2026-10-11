# Kalibracja: ustawienia urządzenia i próby ręczne

Ekrany /calibration i /control używają tych samych ustawień zapisanych na Rider-Pi.
Otwarcie strony odczytuje stan; nie uruchamia usług ani nie uzbraja robota.

## Praca operatora

1. Przygotuj robota, przestrzeń i kabel. Uzbrój raz globalnym przyciskiem.
2. Ustaw siłę polecenia i czas kierunku. Kalibracja udostępnia dodatkowo minimum,
   maksimum, krok suwaka, narastanie i wygaszanie obu osi oraz przerwę nawrotu.
3. Zapisuj między impulsami. Zapis jest dostępny przy ARMED i DISARMED, gdy
   wykonawca potwierdza zerowy cel/wyjście, brak aktywnego czasu polecenia i ruchu.
   Zachowuje uzbrojenie i generację sesji. Nigdy nie wysyła polecenia ruchu.
4. Kliknij strzałkę, oceń ruch, popraw i zapisz. Niezapisany szkic blokuje nowe
   impulsy do potwierdzenia ustawień. Koniec impulsu zatrzymuje napęd bez
   rozbrojenia; STOP rozbraja i unieważnia polecenia w kolejce.
5. Oba ekrany odczytują wspólny zapis. Zmiana rewizji wymaga obejrzenia nastaw
   i ponownego kliknięcia. Konflikt zapisu nie jest automatycznie ponawiany.

Suwaki ustalają polecenie, nie pomiar prędkości. Ocena „za szybko / za wolno”
nie potwierdza metrycznej odometrii. Minimum to wskazany przez operatora próg
użytecznego celu, nie dolna granica każdego pośredniego wyjścia rampy.

## Kontrakt wspólnych ustawień

GET /api/calibration/controls zwraca rider.manual_settings w wersji 2 wewnątrz
dotychczasowej koperty HTTP w wersji 1:

| Pole | Znaczenie |
| --- | --- |
| schema_version | Schemat pliku, obecnie 2. |
| revision | Trwała liczba do kontroli zapisów i dopuszczania ruchu. |
| directions.forward/backward/left/right | minimum, maximum, step, speed, duration. |
| values.speed_limit | Globalny limit polecenia w granicach wdrożenia. |
| values.linear_rate/turn_rate | Narastanie polecenia na sekundę. |
| values.linear_deceleration/turn_deceleration | Wygaszanie polecenia na sekundę. |
| values.reversal_pause | Przerwa w zerze przy zmianie znaku, sekundy. |

Siła 0–1 jest ograniczona globalnym limitem (domyślnie 0.6). Czas 0.01–0.25 s
obejmuje narastanie i wygaszanie. Krótki impuls może nie osiągnąć zadanej wartości.
Panel pokazuje szacowane maksimum polecenia, nie przewidywaną prędkość fizyczną.
Nieosiągalne minimum kierunku jest odrzucane. Zero pozostaje zatrzymaniem.

POST przyjmuje {revision, values, directions}; kierunki i ich pola mogą być
częściowe. Serwer sprawdza świeży, zatrzymany stan oraz rewizję i zapisuje atomowo.
Konflikt lub aktywny impuls: 409; błędne dane: 400; niedostępny magazyn: 503.
Ten endpoint nie wysyła komend.

Strzałki wysyłają device_settings=true, direction i settings_revision w kopercie
bezpieczeństwa. Pi ustala wartości, pojedynczy wykonawca wygładza, adapter zapisuje
UART. Inni producenci poleceń chronionych również podają aktualną rewizję.
Stare rewizje są odrzucane.

Pola zgodności linear_speed i turn_speed odzwierciedlają forward.speed i
right.speed; pulse_duration to największy czas kierunku. Nie są osobnymi
nastawami wykonawcy. Zapis starym formatem jawnie zmienia oba kierunki osi;
nowe klienty powinny korzystać z directions.

## Trwałość i migracja

Plik: ~/.local/state/rider/motion/settings.json poza checkoutem.
RIDER_MANUAL_SETTINGS_PATH pozwala odseparować środowiska. Zapis atomowy, uprawnienia
0600. Jednorazowa migracja zachowuje wcześniej skuteczne wartości z ograniczeniami.
Stary aktywny profil może zasilić pierwszy zapis tylko przy braku magazynu ręcznych
nastaw. Uszkodzony istniejący plik nie przywraca cicho wartości domyślnych.

API archiwalnych profili, pomiarów i odometrii pozostaje. Aktywacja archiwum
nie nadpisuje nastaw ruchu ani nie uzbraja. Archiwum jest źródłem dowodów odometrii,
a nie drugim formularzem konfiguracji ruchu. Autonomia pozostaje zablokowana.

## Znaczenie sprzętowe i bezpieczeństwo

SDK Ridera wysyła cele UART; nie udostępnia sterowania prądem/napięciem silnika.
Siła i tempo zmian nie oznaczają m/s ani fizycznego przyspieszenia.
Wysokość korzysta z natywnego zakresu Ridera 75–115. Figury: 1 sway, 2 vertical,
5 lift_rotate, 6 circular; 255 reset. Postawa i figury pozostają niedostępne
bez potwierdzonej możliwości przerwania. read_motor nie potwierdza enkoderów;
niewiarygodnego yaw nie naprawiamy modulo. Diagnostyka zachowuje surowe dane i czas.

Uzbrojenie panelu jest niezależne od zgody na fizyczne testy. Automatyczne pytest/CI
korzysta z atrap i oddzielnych plików; zgoda panelu nie daje dostępu do sprzętu.
Próby fizyczne wymagają przygotowanego operatora i osobnej konkretnej zgody.

## Proste profile ruchu

Profile są w tym samym pliku ustawień Pi (maksymalnie 16). Każdy zawiera wszystkie
kierunki i wygładzanie. Wybierz profil, następnie „Zastosuj wybrany”: atomowa zmiana
między impulsami, bez uzbrojenia i uruchamiania ruchu. „Zapisz jako nowy” zachowuje
bieżące nastawy oraz widoczny szkic pod wpisaną nazwą. „Aktualizuj wybrany” zastępuje
nastawy profilu i pozwala zmienić nazwę. „Usuń wybrany” usuwa profil, zachowując
bieżące nastawy. Zwykłe „Zapisz ustawienia” zmienia tylko bieżące ustawienia;
ekran oznacza zmieniony aktywny profil. Szkic należy zapisać przed zastosowaniem
innego profilu lub usuwaniem. Konflikt wymaga obejrzenia danych, bez automatycznej
próby nadpisania. Oba ekrany pokazują aktywny profil; zarządzanie jest w Kalibracji.
Nazwy „Biurko”, „Podłoga” opisują zastosowanie operatora; nie narzucamy przykładowej
szybkości ani nie potwierdzamy bezpieczeństwa podłoża. Profile nie podnoszą limitów
wdrożenia i nie odblokowują niezweryfikowanych aktuatorów ani autonomii.
