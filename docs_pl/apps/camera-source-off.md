# Wyłączenie źródła kamery

Oba panele korzystają z `POST /api/resource/camera/pipeline` z akcją `stop`.
Wyłączenie obejmuje źródło obrazu, a nie tylko podgląd lub zadanie panelu.

Po restarcie API przechwytywanie może nadal działać bez odtworzonego zadania.
Jawne OFF odzyskuje takie źródło wyłącznie przy zgodności świeżego statusu
producenta (PID, profil, rewizja i sesja) z dokładną grupą systemd jednej aktywnej
usługi `camera-capture@raw/edge/ssd.service`. Zatrzymanie używa istniejącej warstwy
administracji usług i jej blokady. Brak dowodu własności, inny konsument lub
równoległe źródła nadal powodują odmowę. Zmiana profilu nie przejmuje źródła.

Potwierdzenie wymaga zatrzymanej usługi i statusu producenta; pozytywna odpowiedź
samego backendu systemd nie wystarcza. Powtórzenie identycznego żądania zwraca
zapisany wynik, bez zatrzymania nowszej sesji. Obowiązują dotychczasowe blokady
ruchu i unieważnienie generacji automatu. Operacja nie uzbraja robota.

Odbiór urządzenia: OFF w panelu Pi i Venom, brak procesu przechwytywania,
zwolniony zasób kamery, brak nowych klatek i utrzymanie OFF po odświeżeniu.
Testy programowe działają wyłącznie z atrapą usług w WSL/CI.
