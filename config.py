import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path.home() / ".claude" / ".env", override=False)

# Backend provider: "azure" | "openai" | "codex"
PROVIDER = os.environ.get("CLAUDEGPT_PROVIDER", "azure").lower().strip()

# --- Azure OpenAI ---
AZURE_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
AZURE_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")
AZURE_RESPONSES_API_VERSION = os.environ.get("AZURE_OPENAI_RESPONSES_API_VERSION", "preview")
DEPLOYMENT_OPUS = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT_FULL", "gpt-5-5")
DEPLOYMENT_SONNET = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-54-mini")
DEPLOYMENT_HAIKU = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT_NANO", "gpt-54-nano")

# --- OpenAI direct ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL_OPUS = os.environ.get("CLAUDEGPT_OPENAI_OPUS", "gpt-5.5")
OPENAI_MODEL_SONNET = os.environ.get("CLAUDEGPT_OPENAI_SONNET", "gpt-5.4-mini")
OPENAI_MODEL_HAIKU = os.environ.get("CLAUDEGPT_OPENAI_HAIKU", "gpt-5.4-mini")

# --- Codex (ChatGPT subscription) ---
CODEX_AUTH_PATH = os.environ.get(
    "CLAUDEGPT_CODEX_AUTH", str(Path.home() / ".codex" / "auth.json")
)
CODEX_ENDPOINT = os.environ.get(
    "CLAUDEGPT_CODEX_ENDPOINT",
    "https://chatgpt.com/backend-api/codex/responses",
)
CODEX_MODEL_OPUS = os.environ.get("CLAUDEGPT_CODEX_OPUS", "gpt-5.5")
CODEX_MODEL_SONNET = os.environ.get("CLAUDEGPT_CODEX_SONNET", "gpt-5.4-mini")
CODEX_MODEL_HAIKU = os.environ.get("CLAUDEGPT_CODEX_HAIKU", "gpt-5.4-mini")

# --- Server ---
HOST = os.environ.get("CLAUDEGPT_HOST", "127.0.0.1")
PORT = int(os.environ.get("CLAUDEGPT_PORT", "3210"))

# --- Reasoning effort per Claude tier ---
REASONING_OPUS = os.environ.get("CLAUDEGPT_REASONING_OPUS", "medium")
REASONING_SONNET = os.environ.get("CLAUDEGPT_REASONING_SONNET", "medium")
REASONING_HAIKU = os.environ.get("CLAUDEGPT_REASONING_HAIKU", "medium")
TOOLS_REASONING = os.environ.get("CLAUDEGPT_TOOLS_REASONING", "low")
TOOLS_DEPLOYMENT = os.environ.get("CLAUDEGPT_TOOLS_DEPLOYMENT", "")

# Strip `mcp__*` tool declarations from the request before forwarding to the backend.
# Saves ~30K chars per turn when MCP servers are loaded but not actually used by the model.
# Side effect: model can no longer call any MCP tool. Use case: keep ~/.claude settings
# (CLAUDE.md, commands, permissions) but skip the MCP overhead.
BLOCK_MCP = os.environ.get("CLAUDEGPT_BLOCK_MCP", "").strip().lower() not in ("", "0", "false", "no", "off")

# Comma-separated tool names to drop from the request.  Per-turn savings vary;
# safe defaults below cover tools the user has confirmed unused on this setup.
_DROP_DEFAULT = "NotebookEdit,WebSearch,WebFetch"
DROP_TOOLS = {
    n.strip()
    for n in os.environ.get("CLAUDEGPT_DROP_TOOLS", _DROP_DEFAULT).split(",")
    if n.strip()
}


def map_model(claude_model: str) -> str:
    m = (claude_model or "").lower()
    if PROVIDER == "openai":
        if "haiku" in m:
            return OPENAI_MODEL_HAIKU
        if "opus" in m:
            return OPENAI_MODEL_OPUS
        return OPENAI_MODEL_SONNET
    if PROVIDER == "codex":
        if "haiku" in m:
            return CODEX_MODEL_HAIKU
        if "opus" in m:
            return CODEX_MODEL_OPUS
        return CODEX_MODEL_SONNET
    # azure (default)
    if "haiku" in m:
        return DEPLOYMENT_HAIKU
    if "opus" in m:
        return DEPLOYMENT_OPUS
    if "sonnet" in m:
        return DEPLOYMENT_SONNET
    return DEPLOYMENT_SONNET


def map_reasoning_effort(claude_model: str) -> str:
    m = (claude_model or "").lower()
    if "haiku" in m:
        return REASONING_HAIKU
    if "opus" in m:
        return REASONING_OPUS
    if "sonnet" in m:
        return REASONING_SONNET
    return REASONING_SONNET


def effort_from_thinking(thinking: dict | None) -> str | None:
    """Anthropic `thinking.budget_tokens` (set by Claude Code /effort) → OpenAI reasoning effort."""
    if not isinstance(thinking, dict) or thinking.get("type") != "enabled":
        return None
    budget = thinking.get("budget_tokens", 0)
    try:
        budget = int(budget)
    except (TypeError, ValueError):
        return None
    if budget <= 0:
        return None
    if budget <= 4096:
        return "low"
    if budget <= 12288:
        return "medium"
    return "high"
