import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path.home() / ".claude" / ".env", override=False)

AZURE_ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
AZURE_API_KEY = os.environ["AZURE_OPENAI_API_KEY"]
AZURE_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")

DEPLOYMENT_OPUS = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT_FULL", "gpt-5-5")
DEPLOYMENT_SONNET = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-54-mini")
DEPLOYMENT_HAIKU = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT_NANO", "gpt-54-nano")

HOST = os.environ.get("CLAUDEGPT_HOST", "127.0.0.1")
PORT = int(os.environ.get("CLAUDEGPT_PORT", "3210"))


def map_model(claude_model: str) -> str:
    m = (claude_model or "").lower()
    if "haiku" in m:
        return DEPLOYMENT_HAIKU
    if "opus" in m:
        return DEPLOYMENT_OPUS
    if "sonnet" in m:
        return DEPLOYMENT_SONNET
    return DEPLOYMENT_SONNET
