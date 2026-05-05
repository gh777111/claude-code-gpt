"""Per-turn request/response trace.

Off by default. Enable with `CLAUDEGPT_TRACE=1`.
Output: <repo>/traces/<ts>-<id>.json (or CLAUDEGPT_TRACE_DIR override).
One self-contained JSON file per turn — inspect with `jq` or any editor.
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ENABLED = os.environ.get("CLAUDEGPT_TRACE", "").strip().lower() not in ("", "0", "false", "no", "off")
_DEFAULT_DIR = Path(__file__).parent / "traces"
DIR = Path(os.environ.get("CLAUDEGPT_TRACE_DIR") or _DEFAULT_DIR)


class Trace:
    def __init__(self) -> None:
        self.enabled = ENABLED
        if not self.enabled:
            return
        self.id = uuid.uuid4().hex[:8]
        self._t0 = time.monotonic()
        self._ts_start = datetime.now(timezone.utc)
        self._backend_t0: float | None = None
        self.data: dict = {
            "id": self.id,
            "ts_start": self._ts_start.isoformat(),
        }

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
            DIR.mkdir(parents=True, exist_ok=True)
            ts = self._ts_start.strftime("%Y%m%dT%H%M%S")
            path = DIR / f"{ts}-{self.id}.json"
            path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, default=str))
        except OSError:
            pass  # never break the proxy on trace failures
