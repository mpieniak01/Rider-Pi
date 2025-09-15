# Testy CLI i środowiskowe dla LCD RAW sinka

## 1. Test CLI: RAW sink (na sprzęcie)

Uruchom na docelowym urządzeniu (z zainstalowanym xgoscreen):

```
python3 tools/newface_lcd_direct.py --expr neutral --size 240 --fps 20 --secs 10 --stats --force push_rgb565:rgb565
```

- Oczekiwany efekt: buźka wyświetla się na LCD przez 10 sekund, w konsoli loguje się FPS i metoda pushowania.
- Jeśli chcesz przetestować 3-bajtowy RAW:
```
python3 tools/newface_lcd_direct.py --expr neutral --size 240 --fps 20 --secs 10 --stats --force push_frame_rgb565_3:rgb565_3
```

## 2. Test API: RAW sink (na sprzęcie)

Wywołaj endpoint API (np. przez curl lub narzędzie webowe):

```
curl -X POST 'http://localhost:8000/face/render' \
  -H 'Content-Type: application/json' \
  -d '{"expr": "neutral", "sink": "lcd", "rotate": 270, "spi_hz": 40000000, "method": "push_rgb565"}'
```

- Oczekiwany efekt: render na LCD, brak błędów w logach serwera.

## 3. Test smoke/benchmark

```
python3 tools/newface_lcd_direct.py --expr idle --size 240 --fps 30 --secs 15 --stats --force push_rgb565:rgb565
```

- Oczekiwany efekt: stabilny FPS, brak artefaktów, brak błędów w logach.

## 4. Test fallback (ShowImage)

- (opcjonalnie, tylko na desktopie):
```
python3 tools/newface_lcd_direct.py --expr neutral --size 240 --fps 5 --secs 3 --stats --force ShowImage:pil
```

---

**Uwaga:**
- Przed testami upewnij się, że żaden inny proces nie korzysta z LCD (np. zatrzymaj inne usługi Rider-Pi).
- Parametry `--force` i `--secs` pozwalają wymusić metodę i czas trwania testu.
- Testy CLI można powtarzać dla różnych wyrażeń (`--expr`) i FPS.
