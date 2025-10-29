# services/api_core/local_chat.py
def ask(text: str) -> str:
    # tu Twoja logika lokalnego agenta (np. RAG, heurystyki, Python LLM, itp.)
    return f"[local] otrzymałem: {text}"
