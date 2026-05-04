import json
import uuid


def _system_to_text(system) -> str:
    if not system:
        return ""
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "\n".join(b.get("text", "") for b in system if b.get("type") == "text")
    return str(system)


def _user_blocks(content: list) -> tuple[object, list]:
    parts: list = []
    tool_results: list = []
    extra_images: list = []
    for block in content:
        t = block.get("type")
        if t == "text":
            parts.append({"type": "text", "text": block.get("text", "")})
        elif t == "image":
            src = block.get("source", {})
            if src.get("type") == "base64":
                url = f"data:{src.get('media_type', 'image/png')};base64,{src.get('data', '')}"
            elif src.get("type") == "url":
                url = src.get("url", "")
            else:
                continue
            parts.append({"type": "image_url", "image_url": {"url": url}})
        elif t == "tool_result":
            tr = block.get("content")
            tr_text = ""
            if isinstance(tr, list):
                chunks: list = []
                for b in tr:
                    bt = b.get("type")
                    if bt == "text":
                        chunks.append(b.get("text", ""))
                    elif bt == "image":
                        src = b.get("source", {})
                        if src.get("type") == "base64":
                            url = f"data:{src.get('media_type', 'image/png')};base64,{src.get('data', '')}"
                        elif src.get("type") == "url":
                            url = src.get("url", "")
                        else:
                            continue
                        extra_images.append({"type": "image_url", "image_url": {"url": url}})
                tr_text = "".join(chunks)
            elif isinstance(tr, str):
                tr_text = tr
            elif tr is None:
                tr_text = ""
            else:
                tr_text = json.dumps(tr, ensure_ascii=False)
            tool_results.append({
                "role": "tool",
                "tool_call_id": block.get("tool_use_id"),
                "content": tr_text,
            })
    parts = extra_images + parts
    if parts and all(p.get("type") == "text" for p in parts):
        return "".join(p["text"] for p in parts), tool_results
    return parts, tool_results


def _assistant_blocks(content: list) -> tuple[str, list]:
    text_parts: list = []
    tool_calls: list = []
    for block in content:
        t = block.get("type")
        if t == "text":
            text_parts.append(block.get("text", ""))
        elif t == "tool_use":
            tool_calls.append({
                "id": block.get("id") or f"call_{uuid.uuid4().hex[:24]}",
                "type": "function",
                "function": {
                    "name": block.get("name", ""),
                    "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                },
            })
    return "".join(text_parts), tool_calls


def anthropic_to_openai_messages(req: dict) -> list[dict]:
    msgs: list[dict] = []
    sys_text = _system_to_text(req.get("system"))
    if sys_text.strip():
        msgs.append({"role": "system", "content": sys_text})

    for m in req.get("messages", []):
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, str):
            msgs.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            continue

        if role == "assistant":
            text, tool_calls = _assistant_blocks(content)
            am: dict = {"role": "assistant", "content": text or ""}
            if tool_calls:
                am["tool_calls"] = tool_calls
            msgs.append(am)
        else:
            user_content, tool_results = _user_blocks(content)
            for tr in tool_results:
                msgs.append(tr)
            if isinstance(user_content, str):
                if user_content:
                    msgs.append({"role": "user", "content": user_content})
            elif user_content:
                msgs.append({"role": "user", "content": user_content})
    return msgs


def anthropic_to_openai(req: dict) -> dict:
    body: dict = {
        "messages": anthropic_to_openai_messages(req),
        "stream": bool(req.get("stream", False)),
    }
    if (mt := req.get("max_tokens")):
        body["max_completion_tokens"] = mt
    if (temp := req.get("temperature")) is not None:
        body["temperature"] = temp
    if (top_p := req.get("top_p")) is not None:
        body["top_p"] = top_p
    if (stop := req.get("stop_sequences")):
        body["stop"] = stop

    tools = req.get("tools")
    if tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.get("name"),
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
                },
            }
            for t in tools
        ]
        tc = req.get("tool_choice")
        if tc:
            ct = tc.get("type")
            if ct == "auto":
                body["tool_choice"] = "auto"
            elif ct == "any":
                body["tool_choice"] = "required"
            elif ct == "tool":
                body["tool_choice"] = {
                    "type": "function",
                    "function": {"name": tc.get("name")},
                }

    if body["stream"]:
        body["stream_options"] = {"include_usage": True}

    return body


_STOP_REASON = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "content_filter": "end_turn",
}


def map_finish_reason(fr: str | None) -> str:
    return _STOP_REASON.get(fr or "stop", "end_turn")


def openai_to_anthropic_response(resp: dict, model: str) -> dict:
    choice = resp["choices"][0]
    msg = choice.get("message", {}) or {}
    blocks: list = []
    text = msg.get("content")
    if text:
        blocks.append({"type": "text", "text": text})
    for tc in (msg.get("tool_calls") or []):
        try:
            args = json.loads(tc["function"].get("arguments") or "{}")
        except (json.JSONDecodeError, TypeError):
            args = {}
        blocks.append({
            "type": "tool_use",
            "id": tc.get("id") or f"toolu_{uuid.uuid4().hex[:24]}",
            "name": tc["function"]["name"],
            "input": args,
        })

    usage = resp.get("usage") or {}
    return {
        "id": resp.get("id") or f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": blocks,
        "stop_reason": map_finish_reason(choice.get("finish_reason")),
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }
