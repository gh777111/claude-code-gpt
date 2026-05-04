import json
import uuid
from typing import AsyncIterator


def _sse(event: str, data: dict) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


async def responses_stream_to_anthropic(
    events: AsyncIterator[dict],
    model: str,
) -> AsyncIterator[bytes]:
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"

    yield _sse("message_start", {
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    })

    output_to_anth: dict[int, int] = {}
    output_kind: dict[int, str] = {}
    tool_args_buffer: dict[int, str] = {}
    next_anth_idx = 0
    has_tool_use = False
    output_tokens = 0
    stop_reason = "end_turn"

    async for evt in events:
        et = evt.get("type") or ""

        if et == "response.output_item.added":
            item = evt.get("item") or {}
            oi = evt.get("output_index", 0)
            it = item.get("type")
            if it == "message":
                anth_idx = next_anth_idx
                next_anth_idx += 1
                output_to_anth[oi] = anth_idx
                output_kind[oi] = "text"
                yield _sse("content_block_start", {
                    "type": "content_block_start",
                    "index": anth_idx,
                    "content_block": {"type": "text", "text": ""},
                })
            elif it == "function_call":
                anth_idx = next_anth_idx
                next_anth_idx += 1
                output_to_anth[oi] = anth_idx
                output_kind[oi] = "tool_use"
                has_tool_use = True
                tid = item.get("call_id") or f"toolu_{uuid.uuid4().hex[:24]}"
                yield _sse("content_block_start", {
                    "type": "content_block_start",
                    "index": anth_idx,
                    "content_block": {
                        "type": "tool_use",
                        "id": tid,
                        "name": item.get("name", ""),
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
                    "delta": {"type": "text_delta", "text": evt.get("delta", "")},
                })

        elif et == "response.function_call_arguments.delta":
            oi = evt.get("output_index", 0)
            if output_kind.get(oi) == "tool_use":
                tool_args_buffer[oi] = tool_args_buffer.get(oi, "") + (evt.get("delta") or "")

        elif et == "response.output_item.done":
            oi = evt.get("output_index", 0)
            anth_idx = output_to_anth.get(oi)
            kind = output_kind.get(oi)
            if anth_idx is None:
                continue
            if kind == "tool_use":
                raw = tool_args_buffer.get(oi, "")
                try:
                    parsed = json.loads(raw or "{}")
                    if isinstance(parsed, dict):
                        cleaned = {k: v for k, v in parsed.items()
                                   if v not in ("", None, [])}
                        cleaned_json = json.dumps(cleaned, ensure_ascii=False)
                    else:
                        cleaned_json = raw
                except (json.JSONDecodeError, TypeError):
                    cleaned_json = raw
                if cleaned_json and cleaned_json != "{}":
                    yield _sse("content_block_delta", {
                        "type": "content_block_delta",
                        "index": anth_idx,
                        "delta": {"type": "input_json_delta",
                                  "partial_json": cleaned_json},
                    })
                yield _sse("content_block_stop", {
                    "type": "content_block_stop",
                    "index": anth_idx,
                })
            elif kind == "text":
                yield _sse("content_block_stop", {
                    "type": "content_block_stop",
                    "index": anth_idx,
                })

        elif et == "response.completed":
            resp = evt.get("response") or {}
            usage = resp.get("usage") or {}
            output_tokens = usage.get("output_tokens", output_tokens)
            incomplete = resp.get("incomplete_details") or {}
            if has_tool_use:
                stop_reason = "tool_use"
            elif incomplete.get("reason") == "max_output_tokens":
                stop_reason = "max_tokens"
            else:
                stop_reason = "end_turn"

        elif et == "response.incomplete":
            resp = evt.get("response") or {}
            usage = resp.get("usage") or {}
            output_tokens = usage.get("output_tokens", output_tokens)
            incomplete = resp.get("incomplete_details") or {}
            if incomplete.get("reason") == "max_output_tokens":
                stop_reason = "max_tokens"

        elif et == "response.failed":
            resp = evt.get("response") or {}
            err = resp.get("error") or {}
            payload = {"type": "error",
                       "error": {"type": "api_error",
                                 "message": err.get("message", "responses.failed")}}
            yield f"event: error\ndata: {json.dumps(payload)}\n\n".encode("utf-8")

    yield _sse("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        "usage": {"output_tokens": output_tokens},
    })
    yield _sse("message_stop", {"type": "message_stop"})
