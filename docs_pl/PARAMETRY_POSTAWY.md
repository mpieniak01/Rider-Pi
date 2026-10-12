# Parametry postawy po stronie urządzenia

GET /api/calibration/controls udostępnia parameter_schema.actuator_fields dla wysokości i balansu. Ta sama definicja steruje walidacją HTTP, wykonawcy i adaptera SDK.

- Wysokość: całkowite polecenie SDK, zakres 75–115, krok 1. Nie jest pomiarem wysokości ani wartością określoną w milimetrach.
- Balans: bool kompensacji przechyłu (rider_balance_roll), nie wyłączenie całego regulatora równowagi.
- Capabilities osobno podają dostępność; sam opis parametrów nie udziela zgody na ruch.
- Polecenia używają dotychczasowej koperty manualnej, aktualnej settings_revision i bramy Pi. Odczyt opisu oraz zapis kalibracji nie poruszają urządzeniem.

Definicje źródłowe: common/actuator_parameters.py. Automatyczne sprawdzenia korzystają z atrap; próba fizycznej postawy wymaga zgody operatora.
