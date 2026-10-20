"""OpenAI-compatible Portkey REST client; credentials stay on the Python side."""

import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def load_env(path):
    """Minimal .env subset: KEY=value, comments, optional outer quotes; no expansion."""
    if not Path(path).exists():
        return
    for line_number, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"Invalid .env assignment at line {line_number}")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"Unclosed .env quote at line {line_number}")
            value = value[1:-1]
        os.environ.setdefault(key, value)


class Portkey:
    def __init__(self, model=None, timeout=60):
        self.key = os.environ.get("PORTKEY_API_KEY", "")
        self.model = model or os.environ.get("PORTKEY_MODEL", "")
        self.base_url = os.environ.get("PORTKEY_BASE_URL", "").rstrip("/")
        if not self.key or not self.model or not self.base_url:
            raise ValueError("Fill PORTKEY_API_KEY, PORTKEY_MODEL and PORTKEY_BASE_URL in .env; use demo for an offline run")
        url = urlparse(self.base_url)
        if url.username or url.password or url.query or url.fragment or not url.hostname:
            raise ValueError("Invalid Portkey base URL")
        if url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}):
            raise ValueError("Gateway requires HTTPS, except for a local gateway")
        self.timeout = timeout

    def propose(self, observation, tool_schemas, max_tokens, system_prompt=None):
        prompt = system_prompt or (
            "You edit a Unity top-down key-door maze through allowlisted tools. "
            "Coordinates are x rightwards, y downwards from the top-left, zero indexed. "
            "# wall, . floor, P player, K key, D locked exit, H lethal hazard. "
            "Preserve a wall boundary and exactly one P/K/D. Door blocks movement until key pickup. "
            "Use 1..8 tool calls as one candidate transaction, then read harness feedback. "
            "Lower score is better: unreachable legs first, numeric target error second. "
            "Use the explicit targets as the executable contract; the request supplies design context. "
            "Three zones are vertical thirds of the interior; hazard density is a proxy, not tested difficulty. "
            "Only claim success after evaluation. A finish call cannot override the evaluator."
        )
        payload = {"model": self.model, "messages": [{"role": "system", "content": prompt},
                   {"role": "user", "content": json.dumps(observation, ensure_ascii=False)}],
                   "tools": tool_schemas, "tool_choice": "required", "max_tokens": max_tokens}
        headers = {"Content-Type": "application/json", "x-portkey-api-key": self.key}
        for env_name, header in (("PORTKEY_VIRTUAL_KEY", "x-portkey-virtual-key"), ("PORTKEY_CONFIG", "x-portkey-config")):
            if os.environ.get(env_name):
                headers[header] = os.environ[env_name]
        request = Request(self.base_url + "/chat/completions", data=json.dumps(payload).encode(), headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError("Gateway response exceeds 2 MB")
                data = json.loads(raw)
        except HTTPError as error:
            # Gateway bodies can echo credentials; do not persist or print them.
            raise RuntimeError(f"Portkey HTTP {error.code}; check model routing/key permissions in your workspace") from None
        except (URLError, TimeoutError):
            raise RuntimeError("Portkey connection failed or timed out") from None
        except (UnicodeError, json.JSONDecodeError):
            raise RuntimeError("Portkey returned invalid JSON") from None
        try:
            choice = data["choices"][0]
            calls = choice["message"].get("tool_calls") or []
            usage = data.get("usage") or {}
            metadata = {"model": self.model, "finish_reason": choice.get("finish_reason"),
                        "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0)}
        except (KeyError, IndexError, TypeError, AttributeError):
            raise RuntimeError("Portkey response has no valid completion") from None
        if any(type(metadata[k]) is not int or metadata[k] < 0 for k in ("prompt_tokens", "completion_tokens")):
            raise RuntimeError("Portkey response contains invalid usage counts")
        try:
            actions = [{"name": call["function"]["name"], "arguments": json.loads(call["function"]["arguments"])} for call in calls]
            if choice.get("finish_reason") == "length" or not actions:
                raise ValueError("Missing or truncated tool calls")
        except (KeyError, TypeError, ValueError):
            # Malformed output is a bounded failed step, followed by fresh feedback.
            actions = []
            metadata["protocol_error"] = "Missing, malformed or truncated tool calls"
        return actions, metadata
