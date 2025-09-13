from __future__ import annotations

# Cienki shim – utrzymuje kompatybilność wcześniejszych importów.
# Logika i rejestracja są w chat_glue.py.
from services.api_core import chat_glue as glue  # type: ignore

register = glue.register
chat_history = glue.chat_history
chat_send = glue.chat_send
