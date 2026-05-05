import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

import config
from translate import anthropic_to_responses, responses_to_anthropic
from stream import responses_stream_to_anthropic

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("claudegpt")

_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0))
    try:
        yield
    finally:
        if _client is not None:
            await _client.aclose()


app = FastAPI(lifespan=lifespan, title="claudegpt")


def _read_codex_auth() -> tuple[str, str]:
    with open(config.CODEX_AUTH_PATH) as f:
        d = json.load(f)
    tokens = d.get("tokens") or {}
    return tokens["access_token"], tokens["account_id"]


def _build_request(openai_body: dict) -> tuple[str, dict, dict]:
    """(url, headers, body) per PROVIDER."""
    if config.PROVIDER == "openai":
        url = f"{config.OPENAI_BASE_URL}/responses"
        headers = {
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        return url, headers, openai_body

    if config.PROVIDER == "codex":
        token, account_id = _read_codex_auth()
        url = config.CODEX_ENDPOINT
        headers = {
            "Authorization": f"Bearer {token}",
            "chatgpt-account-id": account_id,
            "OpenAI-Beta": "responses=experimental",
            "Content-Type": "application/json",
        }
        body = dict(openai_body)
        for k in ("max_output_tokens", "temperature", "top_p"):
            body.pop(k, None)
        body["store"] = False
        body["stream"] = True
        if not body.get("instructions"):
            body["instructions"] = "You are a helpful assistant."
        return url, headers, body

    # default: azure
    url = (
        f"{config.AZURE_ENDPOINT}/openai/v1/responses"
        f"?api-version={config.AZURE_RESPONSES_API_VERSION}"
    )
    headers = {"api-key": config.AZURE_API_KEY, "Content-Type": "application/json"}
    return url, headers, openai_body


async def _collect_stream_to_json(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    body: dict,
    model: str,
) -> JSONResponse:
    """Stream from backend, aggregate into a Responses-shaped dict, then
    apply responses_to_anthropic. Used when backend requires stream=true
    but the client requested stream=false."""
    try:
        async with client.stream("POST", url, headers=headers, json=body) as r:
            if r.status_code >= 400:
                err = await r.aread()
                log.warning("Backend collect error %s: %s", r.status_code, err[:500])
                return JSONResponse(
                    status_code=r.status_code,
                    content={"type": "error",
                             "error": {"type": "api_error",
                                       "message": err.decode("utf-8", "replace")[:2000]}},
                )
            response_meta: dict = {}
            items_by_idx: dict[int, dict] = {}
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].lstrip()
                if data == "[DONE]":
                    break
                try:
                    evt = json.loads(data)
                except json.JSONDecodeError:
                    continue
                et = evt.get("type") or ""
                if et == "response.created":
                    response_meta = evt.get("response") or {}
                elif et == "response.output_item.done":
                    items_by_idx[evt.get("output_index", 0)] = evt.get("item") or {}
                elif et in ("response.completed", "response.incomplete"):
                    r_obj = evt.get("response") or {}
                    response_meta = {**response_meta, **r_obj}
            response_meta["output"] = [
                items_by_idx[k] for k in sorted(items_by_idx)
            ]
            return JSONResponse(content=responses_to_anthropic(response_meta, model))
    except httpx.HTTPError as e:
        return JSONResponse(
            status_code=502,
            content={"type": "error", "error": {"type": "api_error", "message": str(e)}},
        )


def _models_summary() -> dict:
    if config.PROVIDER == "openai":
        return {
            "opus": config.OPENAI_MODEL_OPUS,
            "sonnet": config.OPENAI_MODEL_SONNET,
            "haiku": config.OPENAI_MODEL_HAIKU,
        }
    if config.PROVIDER == "codex":
        return {
            "opus": config.CODEX_MODEL_OPUS,
            "sonnet": config.CODEX_MODEL_SONNET,
            "haiku": config.CODEX_MODEL_HAIKU,
        }
    return {
        "opus": config.DEPLOYMENT_OPUS,
        "sonnet": config.DEPLOYMENT_SONNET,
        "haiku": config.DEPLOYMENT_HAIKU,
    }


def _endpoint_summary() -> str:
    if config.PROVIDER == "openai":
        return config.OPENAI_BASE_URL
    if config.PROVIDER == "codex":
        return config.CODEX_ENDPOINT
    return config.AZURE_ENDPOINT


@app.get("/healthz")
async def healthz():
    return {
        "ok": True,
        "provider": config.PROVIDER,
        "endpoint": _endpoint_summary(),
        "models": _models_summary(),
    }


@app.post("/v1/messages/count_tokens")
async def count_tokens(req: Request):
    body = await req.json()
    chars = 0
    sys = body.get("system")
    if isinstance(sys, str):
        chars += len(sys)
    elif isinstance(sys, list):
        chars += sum(len(b.get("text", "")) for b in sys if b.get("type") == "text")
    for m in body.get("messages", []):
        c = m.get("content")
        if isinstance(c, str):
            chars += len(c)
        elif isinstance(c, list):
            for b in c:
                if b.get("type") == "text":
                    chars += len(b.get("text", ""))
    return {"input_tokens": max(1, chars // 4)}


@app.post("/v1/messages")
async def messages(req: Request):
    body = await req.json()
    requested_model = body.get("model", "")
    deployment = config.map_model(requested_model)
    effort = config.map_reasoning_effort(requested_model)
    openai_body = anthropic_to_responses(body, deployment, effort)

    if openai_body.get("tools"):
        openai_body["reasoning"] = {"effort": config.TOOLS_REASONING}
        effort = config.TOOLS_REASONING
        if config.TOOLS_DEPLOYMENT and config.PROVIDER == "azure":
            deployment = config.TOOLS_DEPLOYMENT
            openai_body["model"] = deployment

    # /effort from Claude Code (Anthropic `thinking` field) wins over tier + tools defaults.
    if (override := config.effort_from_thinking(body.get("thinking"))):
        effort = override
        openai_body["reasoning"] = {"effort": effort}

    client_wants_stream = bool(openai_body.get("stream"))
    url, headers, send_body = _build_request(openai_body)
    backend_stream = bool(send_body.get("stream"))

    log.info(
        "→ %s → %s (provider=%s, client_stream=%s, backend_stream=%s, items=%d, effort=%s)",
        requested_model, deployment, config.PROVIDER,
        client_wants_stream, backend_stream,
        len(send_body.get("input", [])), effort,
    )

    client = _client
    assert client is not None

    # Backend forces stream but client wants non-stream: collect SSE → JSON
    if backend_stream and not client_wants_stream:
        return await _collect_stream_to_json(
            client, url, headers, send_body, requested_model
        )

    if not backend_stream:
        try:
            r = await client.post(url, headers=headers, json=send_body)
        except httpx.HTTPError as e:
            return JSONResponse(
                status_code=502,
                content={"type": "error", "error": {"type": "api_error", "message": str(e)}},
            )
        if r.status_code >= 400:
            log.warning("Backend error %s: %s", r.status_code, r.text[:500])
            return JSONResponse(
                status_code=r.status_code,
                content={"type": "error", "error": {"type": "api_error", "message": r.text[:2000]}},
            )
        return JSONResponse(content=responses_to_anthropic(r.json(), requested_model))

    async def stream_gen() -> AsyncIterator[bytes]:
        try:
            async with client.stream("POST", url, headers=headers, json=send_body) as r:
                if r.status_code >= 400:
                    err = await r.aread()
                    log.warning("Backend stream error %s: %s", r.status_code, err[:500])
                    payload = {
                        "type": "error",
                        "error": {
                            "type": "api_error",
                            "message": err.decode("utf-8", "replace")[:2000],
                        },
                    }
                    yield f"event: error\ndata: {json.dumps(payload)}\n\n".encode()
                    return

                async def parsed():
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data:"):
                            data = line[5:].lstrip()
                        else:
                            continue
                        if data == "[DONE]":
                            return
                        try:
                            yield json.loads(data)
                        except json.JSONDecodeError:
                            continue

                async for sse in responses_stream_to_anthropic(parsed(), requested_model):
                    yield sse
        except httpx.HTTPError as e:
            payload = {"type": "error", "error": {"type": "api_error", "message": str(e)}}
            yield f"event: error\ndata: {json.dumps(payload)}\n\n".encode()

    return StreamingResponse(stream_gen(), media_type="text/event-stream")


def main():
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")


if __name__ == "__main__":
    main()
