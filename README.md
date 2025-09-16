This is not an official repository for the Rider-PI robot. It is a sandbox for practicing robot programming.

## rider-face.service (systemd)

Aby włączyć buźkę jako usługę systemd:

```sh
sudo systemctl enable --now rider-face.service   # włączyć i uruchomić
sudo systemctl disable --now rider-face.service  # wyłączyć i zatrzymać
sudo systemctl status rider-face.service         # sprawdzić status
```

Domyślnie rider-face.service jest wyłączony (disabled). Parametry (rotacja/SPI) pobierane z ENV lub domyślne.
