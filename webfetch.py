"""Proxy-side WebFetch implementation.

Anthropic's WebFetch is a server-side tool — Anthropic fetches the URL on its
backend and inlines the result into the assistant message as a
`web_fetch_tool_result` content block.  When proxied through claudegpt, we run
the fetch ourselves (urllib + stdlib HTML parser) and emit the same content
block format so Claude Code sees an identical surface.
"""
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone
from html.parser import HTMLParser

DEFAULT_TIMEOUT = 15
DEFAULT_MAX_CHARS = 50_000
USER_AGENT = "Mozilla/5.0 (compatible; claudegpt-webfetch)"


class _TextExtractor(HTMLParser):
    """Strip tags + collect visible text. Skip script/style/noscript."""

    SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe", "head"}
    BREAK_TAGS = {"p", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6",
                  "tr", "div", "section", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag in self.SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self.BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data):
        if self._in_title:
            self._title_parts.append(data)
            return
        if self._skip_depth == 0:
            self.parts.append(data)

    @property
    def title(self) -> str:
        return "".join(self._title_parts).strip()

    @property
    def text(self) -> str:
        joined = "".join(self.parts)
        joined = re.sub(r"[ \t]+", " ", joined)
        joined = re.sub(r"\n[ \t]+", "\n", joined)
        joined = re.sub(r"\n{3,}", "\n\n", joined)
        return joined.strip()


def fetch_url(
    url: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """Synchronous URL fetch. Returns:
      {ok: True, url, title, text, media_type}  on success
      {ok: False, url, error_code, error_message}  on any failure
    """
    if not url or not url.startswith(("http://", "https://")):
        return {
            "ok": False, "url": url or "",
            "error_code": "invalid_url",
            "error_message": "URL must start with http:// or https://",
        }
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/json,application/xhtml+xml,*/*;q=0.5",
            "Accept-Language": "en;q=0.8, ko;q=0.7, *;q=0.5",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = (resp.headers.get_content_type() or "text/plain").lower()
            charset = resp.headers.get_content_charset() or "utf-8"
            raw = resp.read(2_000_000).decode(charset, errors="replace")
            final_url = resp.geturl()

        if "html" in ctype or "xml" in ctype:
            parser = _TextExtractor()
            try:
                parser.feed(raw)
            except Exception:
                pass
            title = parser.title
            text = parser.text
            media_type = "text/plain"
        else:
            title = ""
            text = raw
            media_type = ctype

        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars] + "\n…[truncated]"
            truncated = True

        return {
            "ok": True, "url": final_url,
            "title": title, "text": text,
            "media_type": media_type, "truncated": truncated,
        }
    except urllib.error.HTTPError as e:
        return {"ok": False, "url": url,
                "error_code": "http_error",
                "error_message": f"HTTP {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"ok": False, "url": url,
                "error_code": "url_unavailable",
                "error_message": str(e.reason)}
    except (TimeoutError, OSError) as e:
        return {"ok": False, "url": url,
                "error_code": "timeout", "error_message": str(e)}
    except Exception as e:
        return {"ok": False, "url": url,
                "error_code": "fetch_failed",
                "error_message": f"{type(e).__name__}: {e}"}


def anthropic_result_block(result: dict, tool_use_id: str) -> dict:
    """Build a content_block for `content_block_start` SSE events."""
    if not result.get("ok"):
        return {
            "type": "web_fetch_tool_result",
            "tool_use_id": tool_use_id,
            "content": {
                "type": "web_fetch_tool_result_error",
                "error_code": result.get("error_code", "fetch_failed"),
            },
        }
    return {
        "type": "web_fetch_tool_result",
        "tool_use_id": tool_use_id,
        "content": {
            "type": "web_fetch_result",
            "url": result["url"],
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "content": {
                "type": "document",
                "source": {
                    "type": "text",
                    "media_type": result.get("media_type", "text/plain"),
                    "data": result["text"],
                },
                "title": result.get("title", ""),
                "citations": {"enabled": True},
            },
        },
    }


def text_summary(result: dict, max_chars: int = 30_000) -> str:
    """Compact text payload for feeding back to the model as function_call_output."""
    if not result.get("ok"):
        return f"[web_fetch error: {result.get('error_code')} - {result.get('error_message','')}]"
    lines = [
        f"URL: {result['url']}",
    ]
    if result.get("title"):
        lines.append(f"Title: {result['title']}")
    lines.append("")
    body = result.get("text", "")
    if len(body) > max_chars:
        body = body[:max_chars] + "\n…[truncated]"
    lines.append(body)
    return "\n".join(lines)
