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


_SUMMARIZER_INSTRUCTIONS = (
    "Extract or summarize content from the web page below according to the "
    "user's prompt. Return only the requested information, concisely. If the "
    "prompt is empty or generic, give a brief overview (3-6 lines) covering "
    "what the site/page is about. Output plain text only — no preamble, no "
    "meta commentary."
)


async def _summarize_fetched(
    client: httpx.AsyncClient,
    backend_url: str,
    backend_headers: dict,
    fetched: dict,
    user_prompt: str,
) -> tuple[str, dict | None]:
    """First-stage summary via small model.  Returns (summary_text, usage_or_None).
    On any failure, falls back to webfetch.text_summary (raw extracted text)."""
    if not fetched.get("ok"):
        return webfetch.text_summary(fetched), None
    if not config.WEB_FETCH_SUMMARIZER:
        return webfetch.text_summary(fetched), None

    raw_text = fetched.get("text", "")
    title = fetched.get("title", "")
    url = fetched.get("url", "")
    user_prompt = (user_prompt or "").strip() or "(no specific prompt — provide a brief overview)"

    input_block = (
        f"<user_prompt>\n{user_prompt}\n</user_prompt>\n\n"
        f"<page_url>{url}</page_url>\n"
        f"<page_title>{title}</page_title>\n"
        f"<page_content>\n{raw_text}\n</page_content>"
    )

    body = {
        "model": config.WEB_FETCH_SUMMARIZER,
        "stream": False,
        "instructions": _SUMMARIZER_INSTRUCTIONS,
        "input": input_block,
        "reasoning": {"effort": "low"},
        "max_output_tokens": 1500,
    }
    if config.PROVIDER == "azure":
        body["prompt_cache_retention"] = "24h"

    try:
        r = await client.post(backend_url, headers=backend_headers, json=body, timeout=60)
    except Exception as e:
        return f"[summarizer call failed: {e}]\n\n" + webfetch.text_summary(fetched), None
    if r.status_code >= 400:
        return (
            f"[summarizer http {r.status_code}]\n\n" + webfetch.text_summary(fetched),
            None,
        )

    try:
        resp = r.json()
    except Exception:
        return webfetch.text_summary(fetched), None

    text = ""
    for item in resp.get("output") or []:
        if item.get("type") == "message":
            for c in item.get("content") or []:
                if c.get("type") == "output_text":
                    text += c.get("text", "")
    if not text:
        return webfetch.text_summary(fetched), None
    if len(text) > config.WEB_FETCH_SUMMARY_MAX_CHARS:
        text = text[: config.WEB_FETCH_SUMMARY_MAX_CHARS] + "\n…[truncated]"
    return text, resp.get("usage")


async def _drive_round(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    body: dict,
    cursor: dict,
    pending_fetches: list,
    captured_events: list | None = None,
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
                if captured_events is not None:
                    captured_events.append(evt)

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
                    # The last round's input_tokens reflects the largest accumulated
                    # context (prior input + appended function_call_output blocks).
                    cursor["input_tokens"] = usage.get("input_tokens", cursor["input_tokens"])
                    if saw_real_tool_use:
                        cursor["stop_reason"] = "tool_use"
                    else:
                        cursor["stop_reason"] = "end_turn"

                elif et == "response.incomplete":
                    resp = evt.get("response") or {}
                    usage = resp.get("usage") or {}
                    cursor["output_tokens"] += usage.get("output_tokens", 0)
                    cursor["input_tokens"] = usage.get("input_tokens", cursor["input_tokens"])
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
    *,
    trace=None,
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
        "input_tokens": 0,
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
    rounds_log: list[dict] = []  # one entry per Azure call, captured for the trace
    captured_events: list[dict] | None = [] if (trace is not None and getattr(trace, "enabled", False)) else None
    rounds = 0
    while rounds < config.WEB_FETCH_MAX_CHAIN:
        rounds += 1
        pending: list[dict] = []
        round_events: list[dict] = []
        async for chunk in _drive_round(client, url, headers, current_body,
                                        cursor, pending,
                                        round_events if captured_events is not None else None):
            yield chunk
        if captured_events is not None:
            captured_events.extend(round_events)
            rounds_log.append({"round": rounds, "events": len(round_events),
                               "pending_fetches": len(pending)})
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
            user_prompt = args.get("prompt") or ""
            result = await loop.run_in_executor(
                None,
                lambda u=target_url: webfetch.fetch_url(
                    u,
                    timeout=config.WEB_FETCH_TIMEOUT,
                    max_chars=config.WEB_FETCH_MAX_CHARS,
                ),
            )
            # 1st-stage: small model summarizes/extracts based on `prompt`.
            summary, summarizer_usage = await _summarize_fetched(
                client, url, headers, result, user_prompt,
            )
            fc["fetch_result"] = result
            fc["summary"] = summary
            anth_idx = cursor["anth_idx"]
            cursor["anth_idx"] += 1
            block = webfetch.anthropic_result_block(result, fc["call_id"])
            # Replace the embedded text with the small-model summary so Claude Code
            # surfaces the same compact form Anthropic does.
            if (block.get("content") or {}).get("type") == "web_fetch_result":
                block["content"]["content"]["source"]["data"] = summary
            yield _sse("content_block_start", {
                "type": "content_block_start",
                "index": anth_idx,
                "content_block": block,
            })
            yield _sse("content_block_stop", {
                "type": "content_block_stop", "index": anth_idx,
            })
            if captured_events is not None:
                rounds_log[-1].setdefault("fetches", []).append({
                    "url": target_url,
                    "user_prompt": user_prompt,
                    "ok": result.get("ok"),
                    "title": result.get("title"),
                    "raw_text_len": len(result.get("text", "")),
                    "summary_len": len(summary),
                    "summarizer_usage": summarizer_usage,
                    "error_code": result.get("error_code"),
                    "error_message": result.get("error_message"),
                })

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
                "output": fc.get("summary") or webfetch.text_summary(fc["fetch_result"]),
            })
        current_body = {**current_body, "input": new_input}

    scaled_input = int(cursor["input_tokens"] * config.token_scale(requested_model))
    yield _sse("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": cursor["stop_reason"], "stop_sequence": None},
        "usage": {"input_tokens": scaled_input,
                  "output_tokens": cursor["output_tokens"]},
    })
    yield _sse("message_stop", {"type": "message_stop"})

    if trace is not None and getattr(trace, "enabled", False):
        trace.set(
            chain_rounds=rounds_log,
            response_openai_events=captured_events or [],
        )
