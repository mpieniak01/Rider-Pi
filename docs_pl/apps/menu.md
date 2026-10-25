# Menu na cztery przyciski

Aktualna implementacja czterech przycisków jest w
[apps/menu/main.py](../../apps/menu/main.py). apps/launcher/main.py usunięto;
nie używaj tej ścieżki jako polecenia startu. Osobny [starszy CLI](launcher.md)
to apps/main.py, z innym zachowaniem.

Menu subskrybuje ui.button i motion.state. Obsługuje id=LEFT|RIGHT|OK|BACK,
event=down. LEFT/RIGHT zawijają kursor, OK wybiera, BACK żąda STOP.
Publikuje system.menu.state około raz na sekundę, a system.mode po wyborze.

| Pozycja | Zamiar |
| --- | --- |
| Dema | STOP, następnie system.mode=demos, demo=trajectory |
| Autonomia | STOP, następnie system.mode=autonomy |
| Teleop | STOP, następnie system.mode=teleop |
| Ustawienia / Logi | Placeholdery bez zrealizowanej akcji |

STOP używa motion.command z action=stop, source=manual, origin=physical_menu
i nowym request_id. Publikacja nie potwierdza zatrzymania fizycznego.
Menu nie przyznaje ARM i nie tworzy aktualnej generacji poleceń.

Świeży pomiar baterii poniżej 0.15 blokuje wybór Dema/Autonomia.
Brak pomiaru jest stanem nieznanym; ten warunek menu nie jest pełną bramą
bezpieczeństwa. Konsumenci i aktualny wykonawca pozostają rozstrzygający.
Moduł używa common.bus/ZeroMQ, nie tylko biblioteki standardowej.

[Przyciski](ui.md) · [Brama ruchu](motion.md) ·
[Rzeczywiste mapowanie zadań/usług](../ZADANIA_USLUGI_ZASOBY.md).
Testy izolują BUS, ponieważ zamiar menu może uruchomić konsumenta.
