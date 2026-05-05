# claude-code-gpt

> [Claude Code](https://docs.claude.com/en/docs/claude-code/overview)를 **GPT-5.5** 백엔드로 실행하는 가벼운 프록시 — Azure OpenAI, OpenAI 직접, 또는 기존 Codex CLI 세션을 통해.

<p align="center">
  <img src="docs/img/architecture-ko.png" alt="claude-code-gpt 아키텍처" width="520">
</p>
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

Anthropic Opus를 같은 작업에 직접 사용하면 수 배 더 비쌌을 것입니다. 정식 벤치마크가 아닌 1회 사내 측정치이며, 비용은 작업 종류·프롬프트 크기·sub‑agent 개수에 크게 좌우됩니다.

---

## 빠른 시작

```bash
git clone https://github.com/gh777111/claude-code-gpt
cd claude-code-gpt
uv sync                       # fastapi/uvicorn/httpx/python-dotenv 설치

mkdir -p ~/.local/bin
ln -sf "$PWD/claudegpt" ~/.local/bin/claudegpt
# ~/.local/bin 이 PATH에 있어야 합니다.

claudegpt                     # 첫 실행 시 setup 마법사가 뜹니다
```

마법사가 백엔드(Azure / OpenAI / Codex)를 묻고 `.env`를 자동 생성합니다. Codex를 고르면 `codex login`을 직접 호출 — API 키 복사/붙여넣기 필요 없음.

요구사항:
- macOS / Linux
- Python 3.12 이상
- [`uv`](https://docs.astral.sh/uv/) (또는 `pip install -e .`)
- [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) 설치
- 지원 백엔드 중 최소 하나의 자격증명

---

## 백엔드

`.env`의 `CLAUDEGPT_PROVIDER`로 선택.

### `azure` *(권장)*
```bash
CLAUDEGPT_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://YOUR-RESOURCE.cognitiveservices.azure.com/
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_CHAT_DEPLOYMENT_FULL=gpt-5-5      # → claude-opus-*
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-54-mini       # → claude-sonnet-*
AZURE_OPENAI_CHAT_DEPLOYMENT_NANO=gpt-54-nano  # → claude-haiku-*
```

### `openai`
```bash
CLAUDEGPT_PROVIDER=openai
OPENAI_API_KEY=sk-...
CLAUDEGPT_OPENAI_OPUS=gpt-5.5
CLAUDEGPT_OPENAI_SONNET=gpt-5.4-mini
```

### `codex` *(experimental)*
로컬 Codex CLI 세션(`~/.codex/auth.json`)을 읽어 같은 백엔드로 요청 전달. 업스트림 변경 시 깨질 수 있는 실험 옵션.
```bash
CLAUDEGPT_PROVIDER=codex
# ~/.codex/auth.json 이 먼저 있어야 함 (`codex login`)
```

---

## 모델 매핑

| Claude tier | azure | openai | codex |
| --- | --- | --- | --- |
| opus | `gpt-5-5` | `gpt-5.5` | `gpt-5.5` |
| sonnet | `gpt-54-mini` | `gpt-5.4-mini` | `gpt-5.4-mini` |
| haiku | `gpt-54-nano` | `gpt-5.4-mini` | `gpt-5.4-mini` |

`.env`로 override 가능.

### Reasoning effort

GPT‑5 시리즈는 reasoning 모델 계열입니다. tier별 effort(기본 `medium`)는 설정 가능하며, 도구 호출 turn은 자동으로 `low`로 다운시프트:

```bash
CLAUDEGPT_REASONING_OPUS=medium
CLAUDEGPT_REASONING_SONNET=medium
CLAUDEGPT_REASONING_HAIKU=medium
CLAUDEGPT_TOOLS_REASONING=low
```

런처가 Claude Code의 `--effort` flag(또는 `claudegpt --effort medium`)를 가로채서 모든 tier에 일괄 적용합니다. effort가 바뀌면 프록시 자동 재시작. (Claude Code는 비‑Anthropic 백엔드엔 `thinking`을 안 보내므로 런처에서 환경변수로 우회.)

---

## 웹 도구

Anthropic의 `WebSearch`와 `WebFetch`는 서버 측 도구라 GPT 백엔드에선 그대로 작동 안 합니다. 프록시가 둘 다 GPT 쪽에서 재현해줍니다.

### WebSearch → Azure 호스티드 `web_search`

들어오는 `WebSearch` 도구 정의를 `{"type":"web_search"}` 한 줄로 교체. Azure가 자체 검색 실행, 결과는 모델 응답에 인용 포함해 통합되어 옴.

```bash
CLAUDEGPT_MAP_WEB_SEARCH=1   # default; 0이면 도구 자체 드롭
```

비용: Azure 검색 단가(보통 ~$0.025/회)가 모델 토큰 비용에 추가.

### WebFetch → 로컬 2-stage urllib + 작은모델 요약

Anthropic 원본 아키텍처 그대로:
1. `urllib`로 페이지 fetch
2. 작은 모델(haiku tier)로 사용자 `prompt`에 맞춰 1차 추출
3. 짧은 결과만 메인 모델 컨텍스트로 follow-up

`server_tool_use` + `web_fetch_tool_result` 블록으로 Anthropic 원본과 동일한 형태 emit.

```bash
CLAUDEGPT_MAP_WEB_FETCH=1                          # default
CLAUDEGPT_WEB_FETCH_SUMMARIZER=gpt-54-nano         # 1차 모델; 빈 값이면 비활성
CLAUDEGPT_WEB_FETCH_TIMEOUT=15
CLAUDEGPT_WEB_FETCH_MAX_CHARS=50000                # raw fetch 최대
CLAUDEGPT_WEB_FETCH_SUMMARY_MAX_CHARS=4000         # 1차 출력 최대
CLAUDEGPT_WEB_FETCH_MAX_CHAIN=4                    # 1 turn 최대 fetch 횟수
```

큰 페이지도 메인 모델 컨텍스트는 작게 유지 — Anthropic이 토큰 폭증 막는 같은 트릭.

---

## 도구 정리

도구 declaration을 backend 보내기 전에 선택적으로 차단해서 turn당 수천 토큰 절감 + GPT에선 동작 안 하는 도구 제외.

```bash
# MCP 서버 도구(mcp__*) declaration 모두 제거.
# ~/.claude 설정(CLAUDE.md, commands, 권한)은 그대로 유지하면서
# MCP turn 비용만 빼고 싶을 때.
CLAUDEGPT_BLOCK_MCP=1

# 특정 도구 이름으로 드롭. 기본은 NotebookEdit (대부분 .ipynb 안 만짐).
CLAUDEGPT_DROP_TOOLS=NotebookEdit,Bash      # 예: 셸은 전부 /codex-exec로 위임
```

---

## Tracing

매 turn이 `<repo>/traces/<cwd-tag>/<ts>-<id>.json`에 자기-완결적 JSON으로 기록됩니다. 기본 ON, `CLAUDEGPT_TRACE=0`으로 끔.

```bash
CLAUDEGPT_TRACE=1                          # default
CLAUDEGPT_TRACE_DIR=/path/elsewhere        # default <repo>/traces
```

각 파일은 들어온 Anthropic 요청, 송출 OpenAI body, Azure SSE 이벤트(스트림), 변환된 Anthropic 응답, timing/effort/모델 메타를 모두 포함. WebFetch chain은 `chain_rounds`에 라운드별 정보 기록. `jq` 또는 에디터로 바로 읽을 수 있는 형태.

`traces/`는 .gitignore에 등록 — 사용자 prompt가 들어 있어 commit 금지.

---

## 동작 원리

```
Claude Code
   │
   │  POST /v1/messages   (Anthropic Messages API + SSE)
   ▼
claude-code-gpt  ── 변환 ──►  POST /v1/responses   (OpenAI Responses API)
   ▲                              │
   │  Anthropic-style SSE          │  Responses SSE
   └──────────── 변환 ◄────────────┘
```

핵심 설계 결정:

- **Responses API 사용** — `reasoning_effort` + tools 동시 사용 + 정합한 스트리밍 의미
- **body 필드 순서 = 안정 prefix 먼저** (`instructions` → `tools` → `input`). Azure 자동 prefix 캐시는 첫 1024 토큰 hash 기반이라 boilerplate를 앞에, 변동되는 conversation은 뒤에
- **24시간 캐시 retention** Azure에 자동 주입(`prompt_cache_retention: "24h"`). 기본 5–10분 → 24시간으로 확장. 긴 세션의 prefix 비용 대폭 절감
- **도구 인자 buffer + 정제** — 빈 optional 파라미터(예: Read의 `pages`)를 strip. 도구 호출 거부 루프 차단
- **WebFetch chain 컨트롤러** — 모델이 `function_call(WebFetch)` 발사하면 mid-stream에서 가로채 urllib + 작은 모델 요약 → 결과를 follow-up Azure 호출에 splice → 동일 Anthropic 메시지 봉투에서 계속 스트리밍. `MAX_CHAIN`까지 멀티 fetch
- **글로벌 설정 격리 default** — `CLAUDE_CONFIG_DIR=/tmp/claudegpt-clean-config`로 글로벌 `~/.claude/` 건너뜀. system 프롬프트 오버헤드 ~20k → ~6.6k. `CLAUDEGPT_GLOBAL_ISOLATE=0`으로 복구
- **launcher가 .env 직접 read** — `~/.claude/.env`와 `<repo>/.env`에서 `CLAUDEGPT_*` 키만 grep해 export. 셸 rc 의존 X (IDE 통합 터미널, GUI 런처 등에서도 일관)
- **비용 절감 환경변수** — `DISABLE_NON_ESSENTIAL_MODEL_CALLS=1`, `DISABLE_AUTOCOMPACT=1`, `MAX_THINKING_TOKENS=0` launcher가 자동 export

---

## 한계

- **`cache_control` 마커 기반 Anthropic prompt caching** 자동 변환 안 함. 대신 Azure 자동 prefix 캐시(24h retention) 의존 — 명시적이진 않지만 동작
- **인용 형식**: WebSearch 결과는 인라인 markdown 링크로 옴 (Anthropic 원본의 distinct citation 블록과 다름). 내용은 동일, UI 렌더링만 약간 다름
- **WebFetch는 동적 JS 사이트엔 약함**: 순수 urllib, headless browser 없음. JS 실행 필요한 사이트는 chrome(nav 메뉴 등)만 보일 수 있음. 공개 API, 정적 HTML, SSR 페이지엔 잘 작동
- **모델이 자기를 "Claude"라고 응답할 수 있음** — Claude Code system 프롬프트 페르소나 추종. 실제 라우팅은 프록시 로그/백엔드 청구 대시보드 확인
- **ToS 사용자 책임**

---

## 파일 구조

```
claude-code-gpt/
├── claudegpt          # bash launcher: 프록시 부팅 + env export + claude 실행
├── server.py          # FastAPI 앱, provider 분기, SSE collect-to-json
├── translate.py       # Anthropic Messages ↔ OpenAI Responses 변환
├── stream.py          # Responses SSE → Anthropic SSE (default 드라이버)
├── chain.py           # WebFetch chain controller — mid-stream fetch
├── webfetch.py        # urllib + stdlib HTML→text + Anthropic 형식 result blocks
├── trace.py           # turn별 request/response JSON 덤프 (cwd별 분리)
├── config.py          # env 로딩 + 모델 + reasoning_effort 매핑
├── pyproject.toml     # fastapi / uvicorn / httpx / python-dotenv
└── .env.example
```

소스 7개. framework lock-in 없음.

---

## 라이선스

MIT — [LICENSE](LICENSE) 참조.

[aattaran/deepclaude](https://github.com/aattaran/deepclaude) (Claude Code → DeepSeek)에서 영감. Anthropic / OpenAI / Microsoft와 무관.
