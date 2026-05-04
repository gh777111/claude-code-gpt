# claude-code-gpt

> Run [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) with **GPT‑5** as the backend — through Azure OpenAI, OpenAI direct, or your existing Codex CLI session.

A tiny FastAPI proxy that translates Anthropic's Messages API into the OpenAI **Responses API**. Point Claude Code's `ANTHROPIC_BASE_URL` at it and the entire CLI keeps working — same UX, same tools, same sub‑agents — just running on GPT‑5 instead of Claude.

```
Claude Code  ──►  claude-code-gpt  ──►  Azure / OpenAI / Codex
   (UX)            (this repo)          (cheaper compute)
```

---

## Why

Same Claude Code workflow, dramatically lower cost:

| Setup (sonnet × sonnet sub‑agent run, identical task) | Cost |
| --- | ---: |
| Anthropic Opus direct (estimate) | ~$15+ |
| Azure GPT‑5.5 via this proxy | ~$4 |
| Azure GPT‑5.4‑mini via this proxy | **~$0.43** |

Real measurements from our own runs. Your mileage will vary, but the order of magnitude holds.

---

## Quick start

```bash
git clone https://github.com/YOUR/claude-code-gpt
cd claude-code-gpt
cp .env.example .env
# edit .env with your provider + credentials

uv sync                       # installs fastapi/uvicorn/httpx
ln -sf "$PWD/claudegpt" ~/.local/bin/claudegpt

claudegpt                     # boots the proxy + launches Claude Code
```

Requirements:

- macOS / Linux
- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) (or any PEP 517 installer — `pip install -e .` works too)
- [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) installed

---

## Backends

Set `CLAUDEGPT_PROVIDER` in `.env`.

### `azure` *(recommended for production)*
Uses your Azure OpenAI resource. Bring your own deployments:

```bash
CLAUDEGPT_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://YOUR-RESOURCE.cognitiveservices.azure.com/
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_CHAT_DEPLOYMENT_FULL=gpt-5-5      # → claude-opus-*
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-54-mini       # → claude-sonnet-*
AZURE_OPENAI_CHAT_DEPLOYMENT_NANO=gpt-54-nano  # → claude-haiku-*
```

### `openai`
Uses the public OpenAI API with your `OPENAI_API_KEY`:

```bash
CLAUDEGPT_PROVIDER=openai
OPENAI_API_KEY=sk-...
CLAUDEGPT_OPENAI_OPUS=gpt-5.5
CLAUDEGPT_OPENAI_SONNET=gpt-5.4-mini
```

### `codex` *(experimental)*
Reads the local Codex CLI session at `~/.codex/auth.json` and forwards requests to the same backend the Codex CLI uses. Subject to whatever rate limits / quotas your account has there. May break at any time when the upstream changes — treat as a curiosity, not a contract.

```bash
CLAUDEGPT_PROVIDER=codex
# ~/.codex/auth.json must already exist (run `codex login` first)
```

---

## Model mapping

When Claude Code asks for `claude-opus-*` / `claude-sonnet-*` / `claude-haiku-*`, the proxy routes to your configured model per tier. Defaults:

| Claude tier | azure | openai | codex |
| --- | --- | --- | --- |
| opus | `gpt-5-5` | `gpt-5.5` | `gpt-5.5` |
| sonnet | `gpt-54-mini` | `gpt-5.4-mini` | `gpt-5.4-mini` |
| haiku | `gpt-54-nano` | `gpt-5.4-mini` | `gpt-5.4-mini` |

Override any of them via `.env`.

### Reasoning effort

GPT‑5 series is a reasoning family. Effort per tier (default `medium`) is configurable; tool‑bearing turns are automatically shifted down to `low` to keep agentic latency reasonable:

```bash
CLAUDEGPT_REASONING_OPUS=medium
CLAUDEGPT_REASONING_SONNET=medium
CLAUDEGPT_REASONING_HAIKU=medium
CLAUDEGPT_TOOLS_REASONING=low
```

---

## How it works

```
Claude Code
   │
   │  POST /v1/messages   (Anthropic Messages API + SSE)
   ▼
claude-code-gpt  ── translate ──►  POST /v1/responses   (OpenAI Responses API)
   ▲                                  │
   │  Anthropic-style SSE             │  Responses SSE (response.output_text.delta, etc.)
   └──────────── translate ◄──────────┘
```

Key implementation choices:

- **Responses API**, not chat/completions — required for `reasoning_effort` + tools simultaneously, plus better stream semantics.
- **Tool args buffered + cleaned** — empty optional parameters (e.g. Read's `pages`) are stripped before reaching Claude Code, fixing the most common "tool call rejected" loop.
- **Global config isolation** — by default the launcher exports `CLAUDE_CONFIG_DIR=/tmp/claudegpt-clean-config` so Claude Code skips your global `~/.claude/` (CLAUDE.md, MCP, skills, agents). This alone cut our system‑prompt overhead from ~20k to ~6.6k tokens. Disable with `CLAUDEGPT_GLOBAL_ISOLATE=0` if you want your global setup back.
- **Cost‑cutting envs** — `DISABLE_NON_ESSENTIAL_MODEL_CALLS=1`, `DISABLE_AUTOCOMPACT=1`, `MAX_THINKING_TOKENS=0` exported by the launcher.

---

## Limitations

- **Anthropic-only features that don't translate cleanly:** prompt caching with `cache_control` markers, extended thinking blocks, and some fine-grained MCP behaviors. We don't claim parity, just usability.
- **Built-in WebSearch / WebFetch** are not faked — Claude Code's server-side web tools are Anthropic's, not ours. Use a `crawlee` or Brave‑Search MCP instead.
- **The model will insist it is Claude** when you ask. That's just how strongly it follows the Claude Code system prompt; the routing logs and your provider's billing dashboard are the real source of truth.
- **You are responsible for ToS** — using Claude Code with a non‑Anthropic backend is your call. Same for any backend.

---

## File layout

```
claude-code-gpt/
├── claudegpt          # bash launcher: boots proxy, exports envs, execs `claude`
├── server.py          # FastAPI app, provider dispatch, SSE collect-to-json
├── translate.py       # Anthropic Messages ↔ OpenAI Responses input/output
├── stream.py          # Responses SSE → Anthropic SSE
├── config.py          # env loading + model + reasoning_effort mapping
├── pyproject.toml     # fastapi / uvicorn / httpx / python-dotenv
└── .env.example
```

Four real source files. No framework lock‑in.

---

## License

MIT — see [LICENSE](LICENSE).

Inspired by [aattaran/deepclaude](https://github.com/aattaran/deepclaude) (Claude Code → DeepSeek). Not affiliated with Anthropic, OpenAI, or Microsoft.

---

## 한국어

[Claude Code](https://docs.claude.com/en/docs/claude-code/overview)를 GPT‑5 백엔드로 사용하는 가벼운 프록시입니다. Anthropic Messages API ↔ OpenAI Responses API 변환만 하고, 나머지(도구, sub‑agent, MCP, 슬래시 명령)는 Claude Code가 그대로 처리합니다.

**비용 비교 (동일한 작업 — 한글 타자게임 만들기, sonnet × sonnet sub‑agent):**

| 백엔드 | 비용 |
| --- | ---: |
| Anthropic Opus 직접 (추정) | ~$15+ |
| Azure GPT‑5.5 (이 프록시) | ~$4 |
| Azure GPT‑5.4‑mini (이 프록시) | **~$0.43** |

**빠른 시작:**

```bash
git clone https://github.com/YOUR/claude-code-gpt
cd claude-code-gpt
cp .env.example .env       # 본인 백엔드 정보 입력 (azure / openai / codex)
uv sync
ln -sf "$PWD/claudegpt" ~/.local/bin/claudegpt
claudegpt
```

지원 백엔드: `azure` / `openai` / `codex`. `.env`에 `CLAUDEGPT_PROVIDER` 설정. 자세한 옵션은 위 영문 섹션 참조.

**핵심 설계:**

- Responses API 사용 (chat/completions 대신) — `reasoning_effort` + tools 동시 사용 가능, 스트리밍 의미가 더 정합적
- 도구 인자의 빈 string은 자동 strip — Read 도구의 `pages` 같은 선택 파라미터로 인한 거부 loop 차단
- 글로벌 `~/.claude/` 격리 default — system prompt 오버헤드 ~20k → ~6.6k 토큰
- `MAX_THINKING_TOKENS=0`, `DISABLE_AUTOCOMPACT=1`, `DISABLE_NON_ESSENTIAL_MODEL_CALLS=1` 자동

**알려진 한계:**

- 모델이 자기를 "Claude"라고 말함 — Claude Code의 system prompt 페르소나를 그대로 따르는 것. 실제 라우팅은 프록시 로그와 백엔드 대시보드에서 확인 가능
- 내장 WebSearch/WebFetch는 작동 안 함 — `crawlee` MCP 등으로 대체 권장
- prompt caching의 `cache_control` 마커는 자동 변환 안 됨 (백엔드 자동 캐싱은 동작)

라이선스: MIT. Anthropic / OpenAI / Microsoft와 무관.
