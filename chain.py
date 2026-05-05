"""Streaming controller that intercepts WebFetch tool calls and chains
follow-up Azure responses, producing one continuous Anthropic SSE message.

Replaces a direct call to `responses_stream_to_anthropic` for any turn that
declares WebFetch. The output blocks emitted match Anthropic's native shape:
text → server_tool_use → web_fetch_tool_result → text.
"""
import asyncio
import json
import uuid
from typing import AsyncIterator

import httpx

import config
import webfetch


def _sse(event: str, data: dict) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def _clean_args(raw: str) -> str:
    try:
        parsed = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return raw
    if not isinstance(parsed, dict):
        return raw
    cleaned = {k: v for k, v in parsed.items() if v not in ("", None, [])}
    return json.dumps(cleaned, ensure_ascii=False)


async def _drive_round(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    body: dict,
    cursor: dict,
    pending_fetches: list,
) -> AsyncIterator[bytes]:
    """One Azure call: stream events → Anthropic SSE deltas. WebFetch
    function_calls are emitted as server_tool_use blocks AND queued in
    `pending_fetches` for the caller to handle.

    Does not emit message_start / message_stop — caller manages the envelope.
    """
    output_to_anth: dict[int, int] = {}
    output_kind: dict[int, str] = {}
    output_meta: dict[int, dict] = {}
    saw_real_tool_use = False

    try:
        async with client.stream("POST", url, headers=headers, json=body) as r:
            if r.status_code >= 400:
                err = await r.aread()
                payload = {"type": "error", "error": {
                    "type": "api_error",
                    "message": err.decode("utf-8", "replace")[:2000],
                }}
                yield f"event: error\ndata: {json.dumps(payload)}\n\n".encode()
                cursor["fatal"] = True
                return

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

                if et == "response.output_item.added":
                    item = evt.get("item") or {}
                    oi = evt.get("output_index", 0)
                    it = item.get("type")

                    if it == "message":
                        anth_idx = cursor["anth_idx"]
                        cursor["anth_idx"] += 1
                        output_to_anth[oi] = anth_idx
                        output_kind[oi] = "text"
                        yield _sse("content_block_start", {
                            "type": "content_block_start",
                            "index": anth_idx,
                            "content_block": {"type": "text", "text": ""},
                        })
                    elif it == "function_call":
                        name = item.get("name", "")
                        call_id = item.get("call_id") or f"toolu_{uuid.uuid4().hex[:24]}"
                        if name == "WebFetch" and config.MAP_WEB_FETCH:
                            anth_idx = cursor["anth_idx"]
                            cursor["anth_idx"] += 1
                            output_to_anth[oi] = anth_idx
                            output_kind[oi] = "server_tool_use"
                            output_meta[oi] = {"call_id": call_id,
                                               "name": "web_fetch", "args": ""}
                            yield _sse("content_block_start", {
                                "type": "content_block_start",
                                "index": anth_idx,
                                "content_block": {
                                    "type": "server_tool_use",
                                    "id": call_id,
                                    "name": "web_fetch",
                                    "input": {},
                                },
                            })
                        else:
                            anth_idx = cursor["anth_idx"]
                            cursor["anth_idx"] += 1
                            output_to_anth[oi] = anth_idx
                            output_kind[oi] = "tool_use"
                            saw_real_tool_use = True
                            output_meta[oi] = {"call_id": call_id,
                                               "name": name, "args": ""}
                            yield _sse("content_block_start", {
                                "type": "content_block_start",
                                "index": anth_idx,
                                "content_block": {
                                    "type": "tool_use",
                                    "id": call_id,
                                    "name": name,
                                    "input": {},
                                },
                            })
                    else:
                        output_kind[oi] = "skip"

                elif et == "response.output_text.delta":
                    oi = evt.get("output_index", 0)
                    anth_idx = output_to_anth.get(oi)
                    if anth_idx is not None and output_kind.get(oi) == "text":
                        yield _sse("content_block_delta", {
                            "type": "content_block_delta",
                            "index": anth_idx,
                            "delta": {"type": "text_delta",
                                      "text": evt.get("delta", "")},
                        })

                elif et == "response.function_call_arguments.delta":
                    oi = evt.get("output_index", 0)
                    if output_kind.get(oi) in ("tool_use", "server_tool_use"):
                        output_meta[oi]["args"] = (
                            output_meta[oi].get("args", "")
                            + (evt.get("delta") or "")
                        )

                elif et == "response.output_item.done":
                    oi = evt.get("output_index", 0)
                    anth_idx = output_to_anth.get(oi)
                    kind = output_kind.get(oi)
                    if anth_idx is None:
                        continue
                    if kind in ("tool_use", "server_tool_use"):
                        raw = output_meta[oi].get("args", "")
                        cleaned = _clean_args(raw)
                        if cleaned and cleaned != "{}":
                            yield _sse("content_block_delta", {
                                "type": "content_block_delta",
                                "index": anth_idx,
                                "delta": {"type": "input_json_delta",
                                          "partial_json": cleaned},
                            })
                        yield _sse("content_block_stop", {
                            "type": "content_block_stop",
                            "index": anth_idx,
                        })
                        if kind == "server_tool_use":
                            pending_fetches.append({
                                "call_id": output_meta[oi]["call_id"],
                                "args": output_meta[oi].get("args", ""),
                            })
                    elif kind == "text":
                        yield _sse("content_block_stop", {
                            "type": "content_block_stop",
                            "index": anth_idx,
                        })

                elif et == "response.completed":
                    resp = evt.get("response") or {}
                    usage = resp.get("usage") or {}
                    cursor["output_tokens"] += usage.get("output_tokens", 0)
                    if saw_real_tool_use:
                        cursor["stop_reason"] = "tool_use"
                    else:
                        cursor["stop_reason"] = "end_turn"

                elif et == "response.incomplete":
                    resp = evt.get("response") or {}
                    usage = resp.get("usage") or {}
                    cursor["output_tokens"] += usage.get("output_tokens", 0)
                    incomplete = resp.get("incomplete_details") or {}
                    if incomplete.get("reason") == "max_output_tokens":
                        cursor["stop_reason"] = "max_tokens"

                elif et == "response.failed":
                    resp = evt.get("response") or {}
                    err = resp.get("error") or {}
                    payload = {"type": "error", "error": {
                        "type": "api_error",
                        "message": err.get("message", "responses.failed"),
                    }}
                    yield f"event: error\ndata: {json.dumps(payload)}\n\n".encode()
    except httpx.HTTPError as e:
        payload = {"type": "error", "error": {
            "type": "api_error", "message": str(e),
        }}
        yield f"event: error\ndata: {json.dumps(payload)}\n\n".encode()
        cursor["fatal"] = True


async def stream_with_webfetch(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    body: dict,
    requested_model: str,
) -> AsyncIterator[bytes]:
    """Multi-round streaming controller. Drives Azure once; if the model emits
    a WebFetch function_call, runs urllib + sends a follow-up Azure call with
    the result, all under one Anthropic message envelope.
    """
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"
    cursor = {
        "anth_idx": 0,
        "stop_reason": "end_turn",
        "output_tokens": 0,
        "fatal": False,
    }

    yield _sse("message_start", {
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "model": requested_model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    })

    current_body = body
    rounds = 0
    while rounds < config.WEB_FETCH_MAX_CHAIN:
        rounds += 1
        pending: list[dict] = []
        async for chunk in _drive_round(client, url, headers, current_body,
                                        cursor, pending):
            yield chunk
        if cursor["fatal"]:
            break
        if not pending:
            break  # no WebFetch this round → done

        # Run urllib in executor (avoid blocking the async loop)
        loop = asyncio.get_running_loop()
        for fc in pending:
            try:
                args = json.loads(fc["args"] or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            target_url = args.get("url", "")
            result = await loop.run_in_executor(
                None,
                lambda u=target_url: webfetch.fetch_url(
                    u,
                    timeout=config.WEB_FETCH_TIMEOUT,
                    max_chars=config.WEB_FETCH_MAX_CHARS,
                ),
            )
            anth_idx = cursor["anth_idx"]
            cursor["anth_idx"] += 1
            yield _sse("content_block_start", {
                "type": "content_block_start",
                "index": anth_idx,
                "content_block": webfetch.anthropic_result_block(
                    result, fc["call_id"]),
            })
            yield _sse("content_block_stop", {
                "type": "content_block_stop", "index": anth_idx,
            })
            fc["fetch_result"] = result

        # Build follow-up Azure body — append function_call + function_call_output
        # items to input. Original input order preserved.
        new_input = list(current_body.get("input") or [])
        for fc in pending:
            new_input.append({
                "type": "function_call",
                "call_id": fc["call_id"],
                "name": "WebFetch",
                "arguments": fc["args"] or "{}",
            })
            new_input.append({
                "type": "function_call_output",
                "call_id": fc["call_id"],
                "output": webfetch.text_summary(fc["fetch_result"]),
            })
        current_body = {**current_body, "input": new_input}

    yield _sse("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": cursor["stop_reason"], "stop_sequence": None},
        "usage": {"output_tokens": cursor["output_tokens"]},
    })
    yield _sse("message_stop", {"type": "message_stop"})
