# Historyczny interaktywny CLI

[apps/main.py](../../apps/main.py) to starszy launcher terminalowy, osobny od
[menu czterech przycisków](menu.md). Dawnego apps/launcher/main.py już nie ma.

CLI korzysta z /home/pi/robot/data/flags, może tworzyć/usuwać motion.enable
i estop.on, publikuje stare surowe wiadomości ruchu oraz uruchamia trajectory.py
jako proces potomny. Nazwa demo_trajectory_safe opisuje dawny przepływ flag;
nie potwierdza izolacji ani spełnienia obecnego kontraktu bezpieczeństwa.
Sam import modułu może utworzyć katalog flag.

Flaga plikowa nie jest ARM operatora ani zgodą na automatyczną próbę fizyczną.
Usunięcie starej estop.on nie jest zatwierdzoną metodą kasowania obecnego E-Stop.
Publikacja starego STOP nie jest terminalnym ACK wykonawcy.

Do obsługi stosuj [aktualne sterowanie](../ui/control.md), [bramę ruchu](motion.md)
i [mapowanie zadań/usług](../ZADANIA_USLUGI_ZASOBY.md). Sprawdzenie tego CLI
wymaga atrap plików/procesów i odizolowanego BUS; nie uruchamiaj go jako
programowego smoke na robocie. Działanie fizyczne wymaga osobnego planu operatora.
