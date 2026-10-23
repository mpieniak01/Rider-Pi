export const profileMessages = {
  "vision.reason.navigation_stable_clear": ["Stabilnie potwierdzona wolna droga.", "Free corridor consistently confirmed.", "Freier Korridor stabil bestätigt."],
  "vision.reason.navigation_clear_confirmation": ["Potwierdzanie wolnej drogi na nowych klatkach.", "Confirming a free corridor on fresh frames.", "Freien Korridor mit neuen Bildern bestätigen."],
  "vision.reason.navigation_obstacle_confirmed": ["Przeszkoda w torze potwierdzona w czasie.", "Obstacle in the corridor confirmed over time.", "Hindernis im Korridor zeitlich bestätigt."],
  "vision.reason.navigation_obstacle_confirmation": ["Potwierdzanie obszaru przeszkody.", "Confirming a possible obstacle region.", "Möglichen Hindernisbereich bestätigen."],
  "vision.reason.navigation_local_uncertainty": ["Chwilowa niepewność obrazu.", "Brief image uncertainty.", "Kurze Bildunsicherheit."],
  "vision.reason.navigation_near_obstacle": ["Przeszkoda w bliskiej strefie zatrzymania.", "Obstacle in the near stopping zone.", "Hindernis im nahen Stoppbereich."],
  "vision.reason.navigation_critical_support": ["Silny dowód zagrożenia w torze.", "Strong evidence of a corridor hazard.", "Starker Nachweis einer Gefahr im Korridor."],
  "vision.reason.navigation_geometry_near_obstacle": ["Geometria wykryła kolizję w bliskim obrysie.", "Geometry detected a near body collision.", "Geometrie erkennt eine nahe Kollision mit dem Körper."],
  "vision.reason.navigation_geometry_collision": ["Geometria wykryła przeszkodę w obrysie jazdy.", "Geometry detected an obstacle in the swept body volume.", "Geometrie erkennt ein Hindernis im Fahrvolumen."],
  "vision.reason.navigation_tracking_lost": ["Utrata wiarygodnego śledzenia obrazu.", "Reliable image tracking lost.", "Zuverlässige Bildverfolgung verloren."],
  "vision.reason.navigation_duplicate_frame": ["Powtórzona klatka nie zwiększa potwierdzenia.", "Repeated frames cannot increase confirmation.", "Wiederholte Bilder erhöhen die Bestätigung nicht."],
  "vision.reason.navigation_frame_gap": ["Przerwa w klatkach — historia wygasła.", "Frame gap — evidence history expired.", "Bildlücke — Nachweisverlauf abgelaufen."],
  "vision.reason.navigation_context_changed": ["Zmieniono źródło lub politykę — nowa kwalifikacja.", "Source or policy changed — fresh qualification required.", "Quelle oder Richtlinie geändert — neue Qualifizierung nötig."],
  "vision.reason.navigation_time_discontinuity": ["Niespójny czas źródła obrazu.", "Discontinuous source image time.", "Inkonsistente Zeit der Bildquelle."],
  "vision.reason.navigation_invalid_evidence": ["Brak wiarygodnych danych do oceny.", "No reliable evidence for assessment.", "Keine zuverlässigen Nachweise für die Bewertung."],
  "vision.reason.temporal_evidence_unavailable": ["Ocena czasowa jest niedostępna.", "Temporal assessment unavailable.", "Zeitliche Bewertung nicht verfügbar."],
  "vision.reason.temporal_navigation_update_required": ["Nowy profil wymaga zgodnej aktualizacji Venoma i Pi.", "This profile requires compatible Venom and Pi versions.", "Dieses Profil benötigt kompatible Venom- und Pi-Versionen."],
  "behavior.title": [
    "Profil jazdy",
    "Driving profile",
    "Fahrprofil"
  ],
  "behavior.hint": [
    "Wybierz reakcję na szum i krótką niepewność obrazu. STOP operatora, świeżość danych i bliska strefa zatrzymania obowiązują w każdym profilu.",
    "Choose how to handle image noise and brief uncertainty. Operator STOP, data freshness and the near stopping zone apply in every profile.",
    "Reaktion auf Bildrauschen und kurze Unsicherheit wählen. Bediener-STOP, Datenaktualität und Nahbereichsstopp gelten in jedem Profil."
  ],
  "behavior.select": [
    "Profil do zastosowania",
    "Profile to apply",
    "Anzuwendendes Profil"
  ],
  "behavior.profile.legacy": [
    "Dotychczasowy (Legacy)",
    "Previous (Legacy)",
    "Bisherig (Legacy)"
  ],
  "behavior.profile.cautious": [
    "Ostrożny",
    "Cautious",
    "Vorsichtig"
  ],
  "behavior.profile.balanced": [
    "Zrównoważony",
    "Balanced",
    "Ausgewogen"
  ],
  "behavior.profile.fluid": [
    "Płynny",
    "Fluid",
    "Flüssig"
  ],
  "behavior.description.legacy": [
    "Dotychczasowa ocena pojedynczych wyników modelu; zachowana dla zgodności.",
    "Established evaluation of individual model results, retained for compatibility.",
    "Bisherige Bewertung einzelner Modellergebnisse für die Kompatibilität."
  ],
  "behavior.description.cautious": [
    "Mniejsza tolerancja krótkiej niepewności i wcześniejsze ostrzeganie. Parametry pochodzą z urządzenia.",
    "Lower tolerance for brief uncertainty and earlier warnings. Parameters come from the device.",
    "Geringere Toleranz kurzer Unsicherheit und frühere Warnungen. Parameter kommen vom Gerät."
  ],
  "behavior.description.balanced": [
    "Równowaga między potwierdzaniem obszarów w czasie a płynnością jazdy. Parametry pochodzą z urządzenia.",
    "Balances temporal region confirmation and driving continuity. Parameters come from the device.",
    "Gleichgewicht zwischen zeitlicher Bereichsbestätigung und Fahrkontinuität. Parameter kommen vom Gerät."
  ],
  "behavior.description.fluid": [
    "Większa tolerancja krótkiego szumu przy potwierdzonym bliskim torze. Nie wyłącza zatrzymania ani kontroli świeżości.",
    "More tolerance for brief noise with a confirmed near corridor. Stops and freshness checks remain active.",
    "Höhere Toleranz kurzen Rauschens bei bestätigtem Nahkorridor. Stopp und Aktualitätsprüfung bleiben aktiv."
  ],
  "behavior.experimental": [
    "Eksperymentalny",
    "Experimental",
    "Experimentell"
  ],
  "behavior.experimentalHint": [
    "Profil wymaga lokalnego odbioru. Zastosowanie zapisuje tryb obserwacji i kasuje odbiór jazdy; nie uruchamia kamery ani ruchu.",
    "This profile needs local acceptance. Applying selects observation and clears driving acceptance; it starts neither camera nor motion.",
    "Dieses Profil erfordert lokale Abnahme. Anwenden wählt Beobachtung und löscht die Fahrfreigabe; Kamera und Bewegung werden nicht gestartet."
  ],
  "behavior.apply": [
    "Zastosuj profil — obserwacja",
    "Apply profile — observation",
    "Profil anwenden — Beobachtung"
  ],
  "behavior.applyHint": [
    "Zapisz wyłącznie wybrany profil we wspólnej konfiguracji Pi. Kamera zachowuje swój stan.",
    "Save only the selected profile in the shared Pi configuration. The camera keeps its state.",
    "Nur das gewählte Profil in der gemeinsamen Pi-Konfiguration speichern. Der Kamerazustand bleibt erhalten."
  ],
  "behavior.saving": [
    "Zapisywanie…",
    "Saving…",
    "Speichern…"
  ],
  "behavior.refresh": [
    "Odśwież profil",
    "Refresh profile",
    "Profil aktualisieren"
  ],
  "behavior.discard": [
    "Odrzuć wybór i odśwież",
    "Discard choice and refresh",
    "Auswahl verwerfen und aktualisieren"
  ],
  "behavior.current": [
    "Zapisany: {profile} · konfiguracja r{revision}",
    "Saved: {profile} · configuration r{revision}",
    "Gespeichert: {profile} · Konfiguration r{revision}"
  ],
  "behavior.draft": [
    "Oczekuje na zastosowanie: {profile}",
    "Pending application: {profile}",
    "Ausstehende Anwendung: {profile}"
  ],
  "behavior.saved": [
    "Profil zapisany w konfiguracji r{revision}. Obserwacja i ruch wymagają osobnej decyzji operatora.",
    "Profile saved in configuration r{revision}. Observation and motion require separate operator intent.",
    "Profil in Konfiguration r{revision} gespeichert. Beobachtung und Bewegung erfordern eine eigene Bedienerentscheidung."
  ],
  "behavior.parameters": [
    "Parametry profilu — tylko odczyt",
    "Profile parameters — read only",
    "Profilparameter — schreibgeschützt"
  ],
  "behavior.effectiveHash": [
    "SHA-256 efektywnej polityki",
    "Effective policy SHA-256",
    "SHA-256 der wirksamen Richtlinie"
  ],
  "behavior.unsupported": [
    "Urządzenie nie udostępnia zgodnego katalogu profili. Zachowaj dotychczasowy profil; wybór jest niedostępny.",
    "The device does not provide a compatible profile catalog. Keep the established profile; selection is unavailable.",
    "Das Gerät bietet keinen kompatiblen Profilkatalog. Bisheriges Profil beibehalten; Auswahl nicht verfügbar."
  ],
  "behavior.conflict": [
    "Konfigurację zmieniono w drugim panelu. Odrzuć wybór, odśwież stan i wybierz ponownie.",
    "Configuration changed in another panel. Discard the draft, refresh and choose again.",
    "Die Konfiguration wurde im anderen Panel geändert. Auswahl verwerfen, aktualisieren und erneut wählen."
  ],
  "behavior.failed": [
    "Nie zapisano profilu. Odśwież stan i sprawdź przyczynę w diagnostyce.",
    "Profile was not saved. Refresh the state and check diagnostics.",
    "Profil wurde nicht gespeichert. Zustand aktualisieren und Diagnose prüfen."
  ],
  "behavior.block.offline": [
    "Połącz urządzenie, aby zmienić profil.",
    "Connect the device to change its profile.",
    "Zum Profilwechsel das Gerät verbinden."
  ],
  "behavior.block.stale": [
    "Brak aktualnego stanu sterowania. Odśwież połączenie przed zmianą profilu.",
    "Current control state is unavailable. Refresh the connection before changing the profile.",
    "Aktueller Steuerungszustand fehlt. Vor dem Profilwechsel Verbindung aktualisieren."
  ],
  "behavior.block.motion": [
    "Wstrzymaj automat i zakończ ruch przed zmianą profilu. Ręczne sterowanie i STOP pozostają dostępne.",
    "Pause automation and finish movement before changing the profile. Manual control and STOP remain available.",
    "Automatik pausieren und Bewegung vor dem Profilwechsel beenden. Manuelle Steuerung und STOP bleiben verfügbar."
  ],
  "behavior.block.observation": [
    "Zakończ pętlę obserwacji przed zmianą profilu. Kamera może pozostać włączona.",
    "End the observation loop before changing the profile. The camera may remain on.",
    "Vor dem Profilwechsel die Beobachtungsschleife beenden. Die Kamera kann eingeschaltet bleiben."
  ],
  "behavior.block.busy": [
    "Zakończ lub odrzuć inne zmiany ustawień.",
    "Finish or discard other settings changes.",
    "Andere Einstellungsänderungen abschließen oder verwerfen."
  ],
  "temporal.title": [
    "Ocena obrazu w czasie",
    "Temporal image assessment",
    "Zeitliche Bildbewertung"
  ],
  "temporal.raw": [
    "Surowy wynik modelu",
    "Raw model result",
    "Rohes Modellergebnis"
  ],
  "temporal.stabilized": [
    "Ocena po stabilizacji",
    "Stabilized assessment",
    "Stabilisierte Bewertung"
  ],
  "temporal.risk": [
    "Ryzyko / reakcja",
    "Risk / action",
    "Risiko / Reaktion"
  ],
  "temporal.reason": [
    "Przyczyna polityki",
    "Policy reason",
    "Grund der Richtlinie"
  ],
  "temporal.evidence": [
    "Różne klatki dowodowe",
    "Distinct evidence frames",
    "Verschiedene Belegbilder"
  ],
  "temporal.near": [
    "Bliski tor potwierdzony",
    "Near corridor confirmed",
    "Nahkorridor bestätigt"
  ],
  "temporal.boundary": [
    "Punkty granicy w obrazie",
    "Image boundary points",
    "Grenzpunkte im Bild"
  ],
  "temporal.noBoundary": [
    "Brak potwierdzonej granicy; nie jest to pomiar odległości.",
    "No confirmed boundary; this is not a distance measurement.",
    "Keine bestätigte Grenze; dies ist keine Entfernungsmessung."
  ],
  "temporal.none": [
    "Ten wynik nie zawiera oceny czasowej. Obowiązuje pokazana ocena dotychczasowa.",
    "This result has no temporal assessment. The displayed established assessment applies.",
    "Dieses Ergebnis enthält keine zeitliche Bewertung. Die angezeigte bisherige Bewertung gilt."
  ],
  "temporal.historical": [
    "Wynik historyczny lub nieaktualny — nie potwierdza pozwolenia na ruch.",
    "Historical or stale result — does not confirm movement permission.",
    "Historisches oder veraltetes Ergebnis — bestätigt keine Bewegungsfreigabe."
  ],
  "temporal.noReason": [
    "Brak przyczyny w wyniku",
    "No reason in the result",
    "Kein Grund im Ergebnis"
  ],
  "temporal.yes": [
    "Tak",
    "Yes",
    "Ja"
  ],
  "temporal.no": [
    "Nie",
    "No",
    "Nein"
  ],
  "temporal.unknown": [
    "Nieznany",
    "Unknown",
    "Unbekannt"
  ]
};
export function profileText(key, values = {}) {
  const locale = document.documentElement.lang;
  const index = locale.startsWith('en') ? 1 : locale.startsWith('de') ? 2 : 0;
  let value = profileMessages[key]?.[index] || key;
  for (const [name, replacement] of Object.entries(values)) value = value.replaceAll('{'+name+'}', String(replacement));
  return value;
}
