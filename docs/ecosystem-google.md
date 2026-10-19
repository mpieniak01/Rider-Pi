# Google Gemini SDK — disabled

Google SDK voice integration is currently disabled. The ASR, TTS and chat adapters,
demo configurations, SDK tests and development dependencies have been removed.
Legacy `google` / `gemini` selections fail explicitly, without importing an SDK,
calling Google or silently selecting another provider.

Use a supported configuration from [voice configuration](config/voice.md), such as
`voice.toml` for local Piper/Vosk and the existing Venom transport. Google Home
OAuth and feed integration are independent and retain their existing configuration.
