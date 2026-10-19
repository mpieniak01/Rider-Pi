# Google Gemini SDK — wyłączone

Integracja głosowa Google SDK jest obecnie wyłączona. Usunięto adaptery ASR, TTS
i czatu, konfiguracje demonstracyjne, testy SDK oraz zależności deweloperskie.
Stare ustawienia `google` / `gemini` zwracają jawny błąd, bez importowania SDK,
wywoływania Google ani automatycznego wyboru innego dostawcy.

Wybierz obsługiwaną [konfigurację głosu](config/voice.md), np. `voice.toml` dla
lokalnego Piper/Vosk i dotychczasowego transportu Venom. Integracja Google Home
OAuth i feed są niezależne i zachowują dotychczasową konfigurację.
