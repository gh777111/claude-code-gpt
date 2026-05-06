"""Per-turn request/response trace.

Default ON (set CLAUDEGPT_TRACE=0 to disable).
Output: <repo>/traces/<cwd-tag>/<ts>-<id>.json — one file per turn, grouped
by the directory claudegpt was launched from (CLAUDEGPT_CWD env, set by the
launcher). Mirrors how Claude Code keeps sessions per project root.
Override base dir with CLAUDEGPT_TRACE_DIR.
"""
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# default ON; explicit off via CLAUDEGPT_TRACE=0|false|no|off
ENABLED = os.environ.get("CLAUDEGPT_TRACE", "1").strip().lower() not in ("0", "false", "no", "off")
_DEFAULT_DIR = Path(__file__).parent / "traces"
BASE_DIR = Path(os.environ.get("CLAUDEGPT_TRACE_DIR") or _DEFAULT_DIR)


def _cwd_tag(cwd: str | None = None) -> str:
    """Stable, filesystem-safe label derived from the launching cwd."""
    raw = cwd or os.environ.get("CLAUDEGPT_CWD") or os.getcwd()
    # last two path components, slugified — keeps it human-readable + unique enough
    parts = [p for p in raw.split(os.sep) if p][-2:]
    slug = "-".join(parts) or "root"
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", slug)
    return slug[:64] or "root"


class Trace:
    def __init__(self) -> None:
        self.enabled = ENABLED
        if not self.enabled:
            return
        self.id = uuid.uuid4().hex[:8]
        self._t0 = time.monotonic()
        self._ts_start = datetime.now(timezone.utc)
        self._backend_t0: float | None = None
        self._cwd_override: str | None = None
        self.data: dict = {
            "id": self.id,
            "ts_start": self._ts_start.isoformat(),
            "cwd": os.environ.get("CLAUDEGPT_CWD") or os.getcwd(),
        }

    def set_cwd(self, cwd: str) -> None:
        """Override cwd from the request itself (system prompt's
        'Primary working directory'), since the proxy daemon is shared
        across sessions and its env-var cwd is stale."""
        if not self.enabled or not cwd:
            return
        self._cwd_override = cwd
        self.data["cwd"] = cwd

    def set(self, **kw) -> None:
        if not self.enabled:
            return
        self.data.update(kw)

    def backend_start(self) -> None:
        if not self.enabled:
            return
        self._backend_t0 = time.monotonic()

    def backend_end(self) -> None:
        if not self.enabled or self._backend_t0 is None:
            return
        self.data["backend_ms"] = round((time.monotonic() - self._backend_t0) * 1000)

    def save(self) -> None:
        if not self.enabled:
            return
        self.data["duration_ms"] = round((time.monotonic() - self._t0) * 1000)
        self.data.setdefault("ts_end", datetime.now(timezone.utc).isoformat())
        try:
            out_dir = BASE_DIR / _cwd_tag(self._cwd_override)
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = self._ts_start.strftime("%Y%m%dT%H%M%S")
            (out_dir / f"{ts}-{self.id}.json").write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2, default=str)
            )
        except OSError:
            pass  # never break the proxy on trace failures
