SONNET = "anthropic/claude-sonnet-4.6"
OPUS = "anthropic/claude-opus-4.6"
CHATGPT = "openai/gpt-5.2"
MINIMAX = "minimax/minimax-m2.5"
GEMINI_FLASH = "google/gemini-3-flash-preview"
GEMINI = "google/gemini-3.1-pro-preview"

MODEL_MAP = {k: v for k, v in vars().items() if not k.startswith("_") and isinstance(v, str)}
