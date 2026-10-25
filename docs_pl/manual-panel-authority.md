# Właściciel ręcznego panelu

Stan bezpieczeństwa ogłasza opcjonalne `panel_control: {"version":1,"holder":null}`.
Wersja 1 wiąże ręczne ARM operatora z jednym tymczasowym `panel_id` przeglądarki.
Ten sam identyfikator jest wymagany w ręcznych poleceniach aktuatorów, także
hold i release. Nadal obowiązują generacja, sekwencja, czas, TTL i rewizja nastaw.

`panel_id` to niepusty tekst do 128 znaków. Identyfikuje zamiar, nie jest
poświadczeniem. Pozostaje w pamięci przeglądarki, bez odtwarzania po przeładowaniu;
nie stanowi zgody na fizyczną próbę ruchu.

Inny lub starszy panel nie może odnawiać, zastępować ani zwalniać ruchu
właściciela. Odmowa `panel_owner_mismatch` nie hamuje prawidłowego właściciela.
Jawne przejęcie: DISARM/STOP, odczyt nowej generacji, następnie ARM z nową
tożsamością. Stara generacja nie może wznowić jazdy. Globalne STOP i DISARM
pozostają dostępne bez koperty ruchu lub identyfikatora panelu.

Polecenia legacy bez identyfikatora zachowują dotychczasową obsługę, gdy ARM
nie ma przypisanego właściciela. Nowy klient nie udostępnia kontynuowania jazdy
jednym kliknięciem na Pi bez ogłoszonej funkcji. Przejęcie od starszego panelu
wymaga tego samego STOP, odczytu generacji i ARM.

Rozszerzenie nie zmienia nastaw ani watchdoga. Panel czyta czasy z Pi i wysyła
hold szeregowo. Brak odnowień zeruje cel i wyjście. Lewo/prawo oznacza obrót
w miejscu, a nie jazdę po łuku.

Testy `tests/test_panel_authority.py` i zestawy ruchu używają atrap w pamięci.
Odbiór fizyczny wymaga osobnej próby operatora; ACK i niezerowe wyjście SDK nie
potwierdzają ruchu. [Kontrakt ręczny](api-specs/manual-motion.md).
