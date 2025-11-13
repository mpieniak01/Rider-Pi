# Rider‑Pi Apps — PROJECT

> Rider‑Pi to nazwa urządzenia (sprzętu). Nasz projekt tworzy niezależne oprogramowanie **Rider‑Pi Apps**, które rozwija funkcje autonomii i interakcji ponad to, co dostarcza producent urządzenia.

> Dokument biznesowy (high‑level). Przedstawia **wizję i cele projektu** w języku zrozumiałym biznesowo, z lekkim żargonem technicznym tam, gdzie to ułatwia precyzję. Szczegóły implementacyjne i pełna architektura zostaną opisane w pliku **ARCHITECTURE.md**.

## Wizja projektu

Projekt oparty jest o gotowe rozwiązanie sprzętowe Rider‑Pi. Więcej informacji o urządzeniu można znaleźć na stronie producenta: [Yahboom Rider‑Pi](https://category.yahboom.net/products/rider-pi-robot). To dwukołowy robot edukacyjny oparty na Raspberry Pi 4B, wyposażony m.in. w kamerę HD, mikrofon, ekran LCD 2", żyroskop stabilizujący, serwo regulujące wysokość zawieszenia oraz moduł napędu. Urządzenie pracuje w oparciu o system Raspberry Pi OS, a oprogramowanie można rozwijać w języku Python. Szczegółowe parametry techniczne są dostępne na stronie producenta. Warto zaznaczyć, że zestaw w wersji bazowej nie posiada dedykowanej warstwy czujników zbliżeniowych i kolizyjnych, co stanowi wyzwanie, ale jednocześnie otwiera pole do dalszego rozwoju w ramach Rider‑Pi Apps.

Rider‑Pi Apps to lekki, autonomiczny projekt edukacyjno‑eksperymentalny. Powstał z myślą o osobach prywatnych i pasjonatach technologii, które chcą uczyć się poprzez praktykę i obserwację rozwoju własnego robota. Ma on pełnić rolę towarzysza w prostych, codziennych zadaniach – poruszać się, reagować na głos, wyrażać emocje i w czytelny sposób prezentować swój stan.

Projekt został zaprojektowany jako **energooszczędny** – działa w krótkich cyklach, co pozwala lepiej gospodarować baterią i utrzymywać stabilność pracy. Jest rozwijany iteracyjnie, w fazie edukacyjno‑eksperymentalnej, z wykorzystaniem narzędzi AI (ChatGPT, Codex) wspierających analizę i rozwój. Dzięki temu każda kolejna wersja to krok w stronę większej autonomii i lepszego zrozumienia, jak technologia może współpracować z człowiekiem. Aby zrealizować tę wizję, określiliśmy następujące cele nadrzędne.

## Cele nadrzędne

1. **Autonomia** – umożliwienie robotowi samodzielnego poruszania się w różnych trybach:
   - **Tryb „biurko”** – drobne ruchy i manewry w bezpiecznej, ograniczonej przestrzeni.
   - **Tryb „rozpoznawania terenu”** – skanowanie otoczenia i budowanie prostych map.
   - **Tryb „podążanie za człowiekiem”** – śledzenie sylwetki lub znacznika i utrzymywanie dystansu.
2. **Interakcja głosowa** – reagowanie na krótkie komendy, rozpoznawanie momentu przejścia do dialogu, opcjonalnie rozszerzone o integrację z usługą AI wspierającą rozmowę.
3. **Prezentacja emocji** – wizualizacja stanu robota poprzez prostą mimikę („buźka”) odzwierciedlającą wykonywane zadanie lub przebieg rozmowy.
4. **Monitoring i komunikacja** – możliwość śledzenia trybów i stanu w aplikacji web oraz na ekranie LCD.
5. **Bezpieczeństwo** – mechanizmy awaryjnego zatrzymania, unikanie przeszkód, ograniczenie prędkości i czasu ruchu.

## Wartość biznesowa / użytkowa

Rider‑Pi Apps to projekt edukacyjny i eksperymentalny, w którym łączą się nauka, praktyka i kreatywne podejście do technologii. Pozwala:

- zdobywać wiedzę z zakresu robotyki, AI i interakcji człowiek–maszyna,
- testować w praktyce koncepcje autonomii w bezpiecznej, małej skali,
- doświadczać interakcji z robotem, który nie tylko wykonuje zadania, ale też komunikuje się i wyraża emocje.

Projekt ma charakter otwarty i poszukujący – rozwój jest procesem odkrywania, w którym sprawdzamy, jakie rozwiązania okażą się najbardziej wartościowe i praktyczne. Dzięki publikacji w repozytorium publicznym Rider‑Pi Apps wnosi także wartość dla innych: może inspirować, edukować i być przykładem otwartego podejścia do robotyki i AI.

## Zasady ogólne

Aby osiągnąć powyższe cele, kierujemy się kilkoma prostymi zasadami:

- Rozwój etapami: małe, czytelne iteracje zamiast dużych, ryzykownych zmian.
- Stabilne fundamenty: unikanie częstych zwrotów kierunku projektu.
- Prostota i przejrzystość działania – zarówno w funkcjach, jak i w komunikacji z użytkownikiem.
- Świadome gospodarowanie energią – dodatkowe tryby uruchamiane tylko wtedy, gdy są potrzebne.

## Kamienie milowe (MVP)

Aby uporządkować rozwój projektu i krok po kroku zbliżać się do pełnej autonomii, wyznaczyliśmy następujące etapy:

- **M1**: Buźka ↔ stan (emocje, panel trybów w UI).
- **M2**: Głos (komendy lokalne, integracja z AI do dialogu jako opcja).
- **M3**: Tryb „biurko” + bezpieczeństwo (awaryjne zatrzymanie, unikanie przeszkód).
- **M4**: Tryb „rozpoznawanie terenu” (prosty zapis mapy/śladu).
- **M5**: Tryb „podążanie za człowiekiem” (utrzymywanie dystansu).

---
