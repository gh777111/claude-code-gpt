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
_DROP_DEFAULT = "NotebookEdit"
DROP_TOOLS = {
    n.strip()
    for n in os.environ.get("CLAUDEGPT_DROP_TOOLS", _DROP_DEFAULT).split(",")
    if n.strip()
}

# Replace Anthropic-side WebSearch tool with Azure's hosted {"type":"web_search"}
# so the model can actually search.  Only meaningful for provider=azure.
MAP_WEB_SEARCH = os.environ.get("CLAUDEGPT_MAP_WEB_SEARCH", "1").strip().lower() not in ("0", "false", "no", "off")

# Intercept Anthropic-side WebFetch tool calls in the proxy and run urllib locally,
# emitting `web_fetch_tool_result` content blocks that match Anthropic's native format.
MAP_WEB_FETCH = os.environ.get("CLAUDEGPT_MAP_WEB_FETCH", "1").strip().lower() not in ("0", "false", "no", "off")
WEB_FETCH_MAX_CHAIN = int(os.environ.get("CLAUDEGPT_WEB_FETCH_MAX_CHAIN", "4"))
WEB_FETCH_TIMEOUT = int(os.environ.get("CLAUDEGPT_WEB_FETCH_TIMEOUT", "15"))
WEB_FETCH_MAX_CHARS = int(os.environ.get("CLAUDEGPT_WEB_FETCH_MAX_CHARS", "50000"))

# Run a small-model first-stage to summarize/extract from the fetched page based
# on the model's `prompt` argument — mirrors Anthropic's WebFetch architecture.
# Empty value disables (raw text passes through to the main model unmodified).
WEB_FETCH_SUMMARIZER = os.environ.get("CLAUDEGPT_WEB_FETCH_SUMMARIZER", DEPLOYMENT_HAIKU)
WEB_FETCH_SUMMARY_MAX_CHARS = int(os.environ.get("CLAUDEGPT_WEB_FETCH_SUMMARY_MAX_CHARS", "4000"))

# --- Context-window scaling for Claude Code auto-compact ---
# Claude Code's auto-compact threshold is derived from what *it* thinks the
# context window is (e.g. claude-opus-4-7[1m] → 1M).  When the actual backend
# is smaller (e.g. gpt-5.4-mini = 400K), Claude Code triggers compact too late.
# Scale reported `input_tokens` by CLIENT_CONTEXT / BACKEND_CONTEXT so Claude
# Code's "we hit 80%" fires when the backend is actually at 80% of its smaller
# window.
CLIENT_CONTEXT_TOKENS = int(os.environ.get("CLAUDEGPT_CLIENT_CONTEXT", "1000000"))
BACKEND_CONTEXT_OPUS = int(os.environ.get("CLAUDEGPT_BACKEND_CONTEXT_OPUS", "1000000"))
BACKEND_CONTEXT_SONNET = int(os.environ.get("CLAUDEGPT_BACKEND_CONTEXT_SONNET", "400000"))
BACKEND_CONTEXT_HAIKU = int(os.environ.get("CLAUDEGPT_BACKEND_CONTEXT_HAIKU", "400000"))


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


def token_scale(claude_model: str) -> float:
    """Multiplier for input_tokens reported back to Claude Code, so its
    auto-compact threshold (based on CLIENT_CONTEXT_TOKENS) fires before the
    backend's smaller window overflows."""
    m = (claude_model or "").lower()
    if "haiku" in m:
        backend = BACKEND_CONTEXT_HAIKU
    elif "opus" in m:
        backend = BACKEND_CONTEXT_OPUS
    elif "sonnet" in m:
        backend = BACKEND_CONTEXT_SONNET
    else:
        backend = BACKEND_CONTEXT_SONNET
    if backend <= 0:
        return 1.0
    return CLIENT_CONTEXT_TOKENS / backend


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
