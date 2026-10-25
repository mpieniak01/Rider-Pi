# Decyzja: ograniczone krzywe polecenia

Status: zrealizowane jako `ramp_mode`, opisane w [krzywych polecenia](motion-curves.md).
Dokument zachowuje uzasadnienie projektu; nie jest planem oczekującego wdrożenia
ani zapisem ustawień konkretnego urządzenia.

Liniowe approach ogranicza zmianę do rate × dt, ale zmienia nachylenie skokowo
na końcach. Samo zmniejszenie tempa nie wygładza tych przejść. Rosnąca krzywa
logarytmiczna ma największe początkowe nachylenie, a Łagodny S łagodzi oba końce.
Interpolacja w niezmienionym czasie liniowym mogłaby przekroczyć ograniczenie
tempa; realizacja wydłuża czas zgodnie z maksymalnym nachyleniem krzywej.

Obecny kontrakt ma trzy tryby: Liniowy, Łagodny S i Logarytmiczny. Nie zapisuje
osobnego parametru łagodności w ms. Pi jest właścicielem nastaw i profili,
a klienci czytają deskryptor. Niezmienione hold zachowuje postęp, nowy cel
wychodzi z bieżącego wyjścia, nawrot przechodzi przez zero, a TTL impulsu nie
jest wydłużany. STOP, watchdog i utrata uprawnienia zerują wyjście bez oczekiwania
na krzywą. Nie wynika z tego podniesienie siły ani minimum.

Testy [tests/test_motion_curves.py](../tests/test_motion_curves.py) sprawdzają
tempo, granice celu, odnowienia hold, release, nawrot, wygaśnięcie impulsu
i migrację profili. To weryfikacja poleceń programowych; fizyczne przyspieszenie
i zatrzymywanie wymagają osobnych pomiarów operatora.
