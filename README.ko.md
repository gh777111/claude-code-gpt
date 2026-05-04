# claude-code-gpt

> [Claude Code](https://docs.claude.com/en/docs/claude-code/overview)를 **GPT‑5** 백엔드로 실행하는 가벼운 프록시 — Azure OpenAI, OpenAI 직접, 또는 기존 Codex CLI 세션을 통해.
>
> [English README](README.md)

Anthropic Messages API ↔ OpenAI Responses API 변환만 하고, 나머지(도구, sub‑agent, MCP, 슬래시 명령)는 Claude Code가 그대로 처리합니다. UX는 그대로, 청구는 본인이 선택한 백엔드로.

```
Claude Code  ──►  claude-code-gpt  ──►  Azure / OpenAI / Codex
   (UX)            (이 레포)            (저렴한 컴퓨팅)
```

---

## 왜?

같은 Claude Code 워크플로우, 더 저렴한 백엔드를 선택할 수 있습니다. 동일 작업(작은 Pygame 데모, sub‑agent 사용, sonnet × sonnet)에서 한 번 측정한 값:

| 백엔드 | 1회 작업 비용 (참고치) |
| --- | ---: |
| Azure GPT‑5.5 (이 프록시) | ~$4 |
| Azure GPT‑5.4‑mini (이 프록시) | **~$0.43** |

Anthropic Opus를 같은 작업에 직접 사용하면 수 배 더 비쌌을 것입니다. 정식 벤치마크가 아닌 1회 사내 측정치이며, 비용은 작업 종류·프롬프트 크기·sub‑agent 개수에 크게 좌우됩니다. 마케팅 수치가 아니라 "프록시가 실제로 동작한다"는 확인 정도로 봐주세요.

---

## 빠른 시작

```bash
git clone https://github.com/gh777111/claude-code-gpt
cd claude-code-gpt
cp .env.example .env
# .env에 provider 선택 + 자격증명 입력
# Azure는 .env의 deployment 이름이 본인 Azure 리소스에 미리 존재해야 합니다.

uv sync                       # fastapi/uvicorn/httpx/python-dotenv 설치

mkdir -p ~/.local/bin
ln -sf "$PWD/claudegpt" ~/.local/bin/claudegpt
# ~/.local/bin 이 PATH에 들어있어야 합니다.

claudegpt                     # 프록시 자동 기동 + Claude Code 실행
```

요구사항:

- macOS / Linux
- Python 3.12 이상
- [`uv`](https://docs.astral.sh/uv/) (또는 `pip install -e .`)
- [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) 설치
- 지원 백엔드 중 최소 하나의 자격증명 (아래 참조)

---

## 백엔드

`.env`의 `CLAUDEGPT_PROVIDER`로 선택.

### `azure` *(권장)*
Azure OpenAI 리소스 사용. 본인 deployment를 직접 지정:

```bash
CLAUDEGPT_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://YOUR-RESOURCE.cognitiveservices.azure.com/
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_CHAT_DEPLOYMENT_FULL=gpt-5-5      # → claude-opus-*
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-54-mini       # → claude-sonnet-*
AZURE_OPENAI_CHAT_DEPLOYMENT_NANO=gpt-54-nano  # → claude-haiku-*
```

### `openai`
공개 OpenAI API + `OPENAI_API_KEY`:

```bash
CLAUDEGPT_PROVIDER=openai
OPENAI_API_KEY=sk-...
CLAUDEGPT_OPENAI_OPUS=gpt-5.5
CLAUDEGPT_OPENAI_SONNET=gpt-5.4-mini
```

### `codex` *(experimental)*
로컬 Codex CLI 세션(`~/.codex/auth.json`)을 읽어 같은 백엔드로 요청 전달. 계정의 rate limit/quota를 그대로 따릅니다. 업스트림이 변경되면 언제든 깨질 수 있어요 — 실험용 옵션으로만.

```bash
CLAUDEGPT_PROVIDER=codex
# ~/.codex/auth.json 이 미리 있어야 함 (먼저 `codex login` 실행)
```

---

## 모델 매핑

Claude Code가 `claude-opus-*` / `claude-sonnet-*` / `claude-haiku-*`를 요청하면 프록시가 tier별로 라우팅합니다. 기본값:

| Claude tier | azure | openai | codex |
| --- | --- | --- | --- |
| opus | `gpt-5-5` | `gpt-5.5` | `gpt-5.5` |
| sonnet | `gpt-54-mini` | `gpt-5.4-mini` | `gpt-5.4-mini` |
| haiku | `gpt-54-nano` | `gpt-5.4-mini` | `gpt-5.4-mini` |

`.env`로 모두 override 가능.

### Reasoning effort

GPT‑5 시리즈는 reasoning 모델 계열입니다. tier별 effort(기본 `medium`)는 설정 가능하며, **도구 호출 turn은 자동으로 `low`로 다운시프트**되어 agentic latency를 잡습니다:

```bash
CLAUDEGPT_REASONING_OPUS=medium
CLAUDEGPT_REASONING_SONNET=medium
CLAUDEGPT_REASONING_HAIKU=medium
CLAUDEGPT_TOOLS_REASONING=low
```

---

## 동작 원리

```
Claude Code
   │
   │  POST /v1/messages   (Anthropic Messages API + SSE)
   ▼
claude-code-gpt  ── 변환 ──►  POST /v1/responses   (OpenAI Responses API)
   ▲                              │
   │  Anthropic-style SSE          │  Responses SSE (response.output_text.delta 등)
   └──────────── 변환 ◄────────────┘
```

핵심 설계 결정:

- **Responses API 사용** (chat/completions 대신) — `reasoning_effort` + tools 동시 사용 가능, 스트리밍 의미가 더 정합적
- **도구 인자 buffer + 정제** — Read 도구의 `pages` 같은 선택 파라미터의 빈 string을 strip해서 도구 호출 거부 loop 차단
- **글로벌 설정 격리 default** — launcher가 `CLAUDE_CONFIG_DIR=/tmp/claudegpt-clean-config` 설정해서 글로벌 `~/.claude/` (CLAUDE.md, MCP, skills, agents)를 건너뜀. system prompt 오버헤드 ~20k → ~6.6k 토큰. 글로벌 설정 그대로 쓰고 싶으면 `CLAUDEGPT_GLOBAL_ISOLATE=0`.
- **비용 절감 환경변수** — launcher가 `DISABLE_NON_ESSENTIAL_MODEL_CALLS=1`, `DISABLE_AUTOCOMPACT=1`, `MAX_THINKING_TOKENS=0` 자동 export

---

## 한계

- **자동 변환이 안 되는 Anthropic 전용 기능들:** `cache_control` 마커 기반 prompt caching, extended thinking blocks, 일부 fine‑grained MCP 동작. 완벽 호환을 주장하지 않습니다 — 실용성 위주.
- **내장 WebSearch / WebFetch 미지원** — Anthropic 서버 측 도구로, 이 프록시는 우회/대체하지 않습니다. `crawlee` MCP 등 별도 도구를 사용하세요.
- **모델이 자기를 "Claude"라고 응답할 수 있음** — Claude Code의 system prompt 페르소나를 그대로 따르는 동작입니다. 실제 라우팅은 프록시 로그와 백엔드 청구 대시보드에서 확인하세요.
- **ToS는 사용자 책임** — Claude Code를 비‑Anthropic 백엔드로 사용하는 건 본인 판단. 다른 백엔드도 마찬가지.

---

## 파일 구조

```
claude-code-gpt/
├── claudegpt          # bash launcher: 프록시 부팅 + env export + claude 실행
├── server.py          # FastAPI 앱, provider 분기, SSE collect-to-json
├── translate.py       # Anthropic Messages ↔ OpenAI Responses input/output
├── stream.py          # Responses SSE → Anthropic SSE
├── config.py          # env 로딩 + 모델 + reasoning_effort 매핑
├── pyproject.toml     # fastapi / uvicorn / httpx / python-dotenv
└── .env.example
```

실제 소스 4개. framework lock‑in 없음.

---

## 라이선스

MIT — [LICENSE](LICENSE) 참조.

[aattaran/deepclaude](https://github.com/aattaran/deepclaude) (Claude Code → DeepSeek)에서 영감. Anthropic / OpenAI / Microsoft와 무관.
