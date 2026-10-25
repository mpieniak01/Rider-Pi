# Indeks konfiguracji

Publiczne wzory są w config/; ustawienia środowiska, sekrety i raporty operacyjne
pozostają lokalne. Właścicieli i zależności określają [polityka konfiguracji](POLICY.md)
i [polityka środowisk](../POLITYKA_SRODOWISK.md).

| Konfiguracja | Przewodnik |
| --- | --- |
| Głos plikowy/strumieniowy | [Voice](voice.md), config/voice_openai_file.toml / voice_openai_streaming.toml |
| Renderowanie i wygląd buźki | [Face](face.md), config/face.toml, [Studio buźki](../FACE_STUDIO.md) |
| Audio i mikser | [ALSA](alsa.md), [WM8960](../audio/wm8960.md) |
| Walidacja i schematy | [Walidacja](validation.md) |
| Wspólne nastawy ręczne/profile | [Kalibracja](../apps/calibration.md), [deskryptory parametrów](../api-specs/manual-motion.md) |
| Źródło/dostawca/transport kamery | [Pipeline kamery](../CAMERA_PIPELINE_V1.md) |
| Parowanie obliczeń | [Venom compute](../COMPUTE_VENOM.md) |
| Modele i wersjonowane presety | [Percepcja](../apps/perception-models.md), [parametry polityki](../vision-policy-parameters.md) |
| Osobna nakładka pomiarowa | [Referencja obrazu](../IMAGE_REFERENCE.md) |

Głos korzysta z CLI, obsługiwanych nadpisań ENV, wybranego TOML
(VOICE_CONFIG/--config) i wartości domyślnych według danego pola.
Sprawdzaj przewodnik i loader; nie każdy klucz TOML ma odpowiednik ENV/CLI.
Walidacja konfiguracji nie instaluje backendu.

## Nadpisania i sekrety lokalne

Zachowuj istniejący .env i prywatne nastawy. Publiczne .env.example zawierają
placeholdery; nadpisanie nimi aktywnego .env usuwa konfigurację.
config/local/ i prywatne env są ignorowane i nie trafiają do załączników PR,
logów, obrazów ani paczek wdrożeniowych. Ignorowanie nie usuwa śledzonego wpisu;
kontroluj staged diff.

Poświadczenia przechowuj w skonfigurowanym prywatnym środowisku usługi/developera
lub chronionym lokalnym env, z prawami pliku 600 tam, gdzie mają zastosowanie.
Nie wklejaj wartości do argumentów/historii powłoki, publicznego TOML ani instrukcji.
Odwołanie env:OPENAI_API_KEY nazywa zmienną; nie jest sekretem i go nie tworzy.
Backendy mają osobne wymagania. Zwykła powłoka/usługa nie wczytuje automatycznie
wszystkich lokalnych plików env — używaj istniejącego loadera lub konfiguracji usługi.

Trwałe magazyny urządzenia mają własne schematy i rewizje. Zmiana wzoru nie
migruje pracującego urządzenia i nie przywraca zgody ruchu. Stosuj opisaną
transakcję API/CAS zamiast edycji aktywnego zapisu w trakcie pracy konsumenta.
Testy programowe korzystają z odizolowanych magazynów tymczasowych.
