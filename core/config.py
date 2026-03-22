import os

APP_SECRET = os.getenv("APP_SECRET", "change-me")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
TZ = os.getenv("TZ", "Europe/Berlin")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

GOOGLE_CLIENT_SECRET_FILE = os.getenv("GOOGLE_CLIENT_SECRET_FILE", "client_secret.json")

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# LLM provider (OpenAI-compatible — works with Groq, Ollama, etc.)
LLM_API_KEY = os.getenv("LLM_API_KEY", "")        # Groq key or "ollama"
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
