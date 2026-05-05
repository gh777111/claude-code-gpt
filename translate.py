import json
import uuid

import config


def _system_to_text(system) -> str:
    if not system:
        return ""
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "\n".join(b.get("text", "") for b in system if b.get("type") == "text")
    return str(system)


def _image_url_from_source(src: dict) -> str | None:
    t = src.get("type")
    if t == "base64":
        return f"data:{src.get('media_type', 'image/png')};base64,{src.get('data', '')}"
    if t == "url":
        return src.get("url") or None
    return None


def _to_responses_input(req: dict) -> list:
    items: list = []
    for m in req.get("messages", []):
        role = m.get("role")
        content = m.get("content")

        if isinstance(content, str):
            kind = "output_text" if role == "assistant" else "input_text"
            items.append({
                "type": "message",
                "role": role,
                "content": [{"type": kind, "text": content}],
            })
            continue
        if not isinstance(content, list):
            continue

        if role == "assistant":
            text_chunks: list = []
            calls: list = []
            for block in content:
                bt = block.get("type")
                if bt == "text":
                    text_chunks.append(block.get("text", ""))
                elif bt == "tool_use":
                    calls.append({
                        "type": "function_call",
                        "call_id": block.get("id"),
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                    })
            text = "".join(text_chunks)
            if text:
                items.append({
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                })
            items.extend(calls)
        else:
            user_parts: list = []
            tool_outputs: list = []
            extra_images: list = []
            for block in content:
                bt = block.get("type")
                if bt == "text":
                    user_parts.append({"type": "input_text", "text": block.get("text", "")})
                elif bt == "image":
                    url = _image_url_from_source(block.get("source", {}))
                    if url:
                        user_parts.append({"type": "input_image", "image_url": url})
                elif bt == "tool_result":
                    tr = block.get("content")
                    tr_text = ""
                    if isinstance(tr, list):
                        chunks: list = []
                        for b in tr:
                            ct = b.get("type")
                            if ct == "text":
                                chunks.append(b.get("text", ""))
                            elif ct == "image":
                                url = _image_url_from_source(b.get("source", {}))
                                if url:
                                    extra_images.append({"type": "input_image", "image_url": url})
                        tr_text = "".join(chunks)
                    elif isinstance(tr, str):
                        tr_text = tr
                    elif tr is None:
                        tr_text = ""
                    else:
                        tr_text = json.dumps(tr, ensure_ascii=False)
                    tool_outputs.append({
                        "type": "function_call_output",
                        "call_id": block.get("tool_use_id"),
                        "output": tr_text,
                    })
            items.extend(tool_outputs)
            full_user = extra_images + user_parts
            if full_user:
                items.append({
                    "type": "message",
                    "role": "user",
                    "content": full_user,
                })
    return items


def anthropic_to_responses(req: dict, deployment: str, reasoning_effort: str | None) -> dict:
    """Build the OpenAI Responses body. Field-order intent: stable prefix first
    (instructions → tools), volatile last (input messages), so Azure's prefix
    cache hashes the same boilerplate across turns."""
    sys_text = _system_to_text(req.get("system"))
    body: dict = {
        "model": deployment,
        "stream": bool(req.get("stream", False)),
    }
    if sys_text.strip():
        body["instructions"] = sys_text
    if reasoning_effort:
        body["reasoning"] = {"effort": reasoning_effort}

    tools = req.get("tools")
    if tools:
        if config.BLOCK_MCP:
            tools = [t for t in tools if not (t.get("name") or "").startswith("mcp__")]
        if config.DROP_TOOLS:
            tools = [t for t in tools if (t.get("name") or "") not in config.DROP_TOOLS]
        converted: list[dict] = []
        for t in tools:
            name = t.get("name") or ""
            # Anthropic WebSearch → Azure hosted web_search tool (real search, server-side)
            if name == "WebSearch" and config.MAP_WEB_SEARCH and config.PROVIDER == "azure":
                converted.append({"type": "web_search"})
                continue
            converted.append({
                "type": "function",
                "name": name,
                "description": t.get("description", ""),
                "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
            })
        body["tools"] = converted
        tc = req.get("tool_choice")
        if tc:
            ct = tc.get("type")
            if ct == "auto":
                body["tool_choice"] = "auto"
            elif ct == "any":
                body["tool_choice"] = "required"
            elif ct == "tool":
                body["tool_choice"] = {"type": "function", "name": tc.get("name")}

    # volatile content goes last so the cacheable prefix above stays stable
    body["input"] = _to_responses_input(req)

    if (mt := req.get("max_tokens")):
        body["max_output_tokens"] = mt
    if (temp := req.get("temperature")) is not None:
        body["temperature"] = temp
    if (top_p := req.get("top_p")) is not None:
        body["top_p"] = top_p

    return body


def _stop_reason(resp: dict, has_tool_use: bool) -> str:
    if has_tool_use:
        return "tool_use"
    incomplete = resp.get("incomplete_details") or {}
    if incomplete.get("reason") == "max_output_tokens":
        return "max_tokens"
    return "end_turn"


def responses_to_anthropic(resp: dict, model: str) -> dict:
    blocks: list = []
    for item in resp.get("output", []) or []:
        it = item.get("type")
        if it == "message":
            for c in item.get("content", []) or []:
                if c.get("type") == "output_text":
                    blocks.append({"type": "text", "text": c.get("text", "")})
        elif it == "function_call":
            try:
                args = json.loads(item.get("arguments") or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            if isinstance(args, dict):
                args = {k: v for k, v in args.items() if v not in ("", None, [])}
            blocks.append({
                "type": "tool_use",
                "id": item.get("call_id") or f"toolu_{uuid.uuid4().hex[:24]}",
                "name": item.get("name", ""),
                "input": args,
            })

    has_tool = any(b.get("type") == "tool_use" for b in blocks)
    usage = resp.get("usage") or {}
    return {
        "id": resp.get("id") or f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": blocks,
        "stop_reason": _stop_reason(resp, has_tool),
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        },
    }
