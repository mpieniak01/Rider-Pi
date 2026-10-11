# Dodatkowe odczyty Rider-Pi

Potwierdzone na kontrolerze R-1.1.6: rejestr 0x65 zawiera 24 bajty,
sześć float32 little-endian: przyspieszenie XYZ oraz roll/pitch/yaw.
Przyspieszenie zawiera grawitację; orientacja osi wymaga pomiaru fizycznego.
Nie jest to odczyt prędkości kół ani prędkości kątowej.

Rejestr 0x02: 0 = przewrócony, 1 = normalny. Stan przewrócenia nie był
wywoływany w diagnostyce. Odczyt informacyjny nie zmienia uzbrojenia.

Jeden właściciel UART: motion-executor. Na R-1.1.6 pakiet zastępuje trzy
osobne odczyty kątów; inne firmware zachowują dotychczasowe odczyty.
Opcjonalne kanały accel_x/y/z (m/s^2) i work_status (code) zachowują czas,
źródło i jakość w rider.telemetry v1. Ich brak nie blokuje ruchu.
Panel Przegląd pobiera je ze wspólnego kontraktu, bez ponownego odczytu UART.
