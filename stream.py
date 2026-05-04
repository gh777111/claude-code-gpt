import json
import uuid
from typing import AsyncIterator

from translate import map_finish_reason


def _sse(event: str, data: dict) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


async def openai_stream_to_anthropic(
    chunks: AsyncIterator[dict],
    model: str,
) -> AsyncIterator[bytes]:
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"
    text_open = False
    text_index = -1
    next_index = 0
    tool_state: dict[int, dict] = {}
    finish_reason: str | None = None
    output_tokens = 0

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

    async for chunk in chunks:
        u = chunk.get("usage")
        if u:
            output_tokens = u.get("completion_tokens", output_tokens)

        choices = chunk.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        delta = choice.get("delta") or {}

        text = delta.get("content")
        if text:
            if not text_open:
                text_index = next_index
                next_index += 1
                yield _sse("content_block_start", {
                    "type": "content_block_start",
                    "index": text_index,
                    "content_block": {"type": "text", "text": ""},
                })
                text_open = True
            yield _sse("content_block_delta", {
                "type": "content_block_delta",
                "index": text_index,
                "delta": {"type": "text_delta", "text": text},
            })

        for tc in (delta.get("tool_calls") or []):
            oai_idx = tc.get("index", 0)
            fn = tc.get("function") or {}
            state = tool_state.get(oai_idx)
            if state is None:
                if text_open:
                    yield _sse("content_block_stop", {
                        "type": "content_block_stop",
                        "index": text_index,
                    })
                    text_open = False
                state = {
                    "anth_idx": next_index,
                    "id": tc.get("id") or "",
                    "name": fn.get("name") or "",
                    "opened": False,
                }
                next_index += 1
                tool_state[oai_idx] = state
            else:
                if tc.get("id"):
                    state["id"] = tc["id"]
                if fn.get("name"):
                    state["name"] = fn["name"]

            if not state["opened"] and state["name"]:
                if not state["id"]:
                    state["id"] = f"toolu_{uuid.uuid4().hex[:24]}"
                yield _sse("content_block_start", {
                    "type": "content_block_start",
                    "index": state["anth_idx"],
                    "content_block": {
                        "type": "tool_use",
                        "id": state["id"],
                        "name": state["name"],
                        "input": {},
                    },
                })
                state["opened"] = True

            args_piece = fn.get("arguments")
            if args_piece and state["opened"]:
                yield _sse("content_block_delta", {
                    "type": "content_block_delta",
                    "index": state["anth_idx"],
                    "delta": {"type": "input_json_delta", "partial_json": args_piece},
                })

        fr = choice.get("finish_reason")
        if fr:
            finish_reason = fr

    if text_open:
        yield _sse("content_block_stop", {
            "type": "content_block_stop",
            "index": text_index,
        })
    for state in tool_state.values():
        if state["opened"]:
            yield _sse("content_block_stop", {
                "type": "content_block_stop",
                "index": state["anth_idx"],
            })

    yield _sse("message_delta", {
        "type": "message_delta",
        "delta": {
            "stop_reason": map_finish_reason(finish_reason),
            "stop_sequence": None,
        },
        "usage": {"output_tokens": output_tokens},
    })
    yield _sse("message_stop", {"type": "message_stop"})
