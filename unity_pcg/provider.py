"""Shared tool-calling REST client for Ollama, LM Studio, and optional Portkey."""

import json
import math
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


class ModelClient:
    def __init__(self, model=None, provider=None, base_url=None, timeout=None):
        self.name = provider or os.environ.get("PCG_PROVIDER") or "ollama"
        defaults = {"ollama": ("OLLAMA", "http://localhost:11434/v1"),
                    "lmstudio": ("LMSTUDIO", "http://localhost:1234/v1"),
                    "portkey": ("PORTKEY", "")}
        if self.name not in defaults:
            raise ValueError("Provider must be ollama, lmstudio or portkey")
        prefix, default_url = defaults[self.name]
        self.model = model or os.environ.get(prefix + "_MODEL", "")
        self.base_url = (base_url or os.environ.get(prefix + "_BASE_URL") or default_url).rstrip("/")
        key = os.environ.get(prefix + "_API_KEY", "")
        if self.name == "portkey" and (not key or not self.model or not self.base_url):
            raise ValueError("Fill PORTKEY_API_KEY, PORTKEY_MODEL and PORTKEY_BASE_URL in .env; use demo for an offline run")
        if not self.model:
            raise ValueError(f"Set {prefix}_MODEL or pass --model; choose an installed tool-calling model")
        url = urlparse(self.base_url)
        if url.username or url.password or url.query or url.fragment or not url.hostname:
            raise ValueError(f"Invalid {self.name} base URL")
        if url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}):
            raise ValueError("Model endpoint requires HTTPS, except on localhost")
        self.timeout = float(timeout if timeout is not None else os.environ.get("PCG_MODEL_TIMEOUT") or 120)
        if not math.isfinite(self.timeout) or not 1 <= self.timeout <= 1800:
            raise ValueError("Model timeout must be 1..1800 seconds")
        self.headers = {"Content-Type": "application/json"}
        if self.name == "portkey":
            self.headers["x-portkey-api-key"] = key
            for env_name, header in (("PORTKEY_VIRTUAL_KEY", "x-portkey-virtual-key"), ("PORTKEY_CONFIG", "x-portkey-config")):
                if os.environ.get(env_name):
                    self.headers[header] = os.environ[env_name]
        elif key:
            self.headers["Authorization"] = "Bearer " + key

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
                   "tools": tool_schemas, "stream": False, "max_tokens": max_tokens}
        # Local runtimes/models differ in forced-tool support; missing calls still fail the protocol.
        if self.name == "portkey":
            payload["tool_choice"] = "required"
        request = Request(self.base_url + "/chat/completions", data=json.dumps(payload).encode(), headers=self.headers, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError("Model response exceeds 2 MB")
                data = json.loads(raw)
        except HTTPError as error:
            # Server bodies can echo credentials or prompts; do not persist or print them.
            raise RuntimeError(f"{self.name} HTTP {error.code}; check server, model ID, tool support and authentication") from None
        except (URLError, TimeoutError):
            raise RuntimeError(f"{self.name} connection failed or timed out; start the server or check base URL and PCG_MODEL_TIMEOUT") from None
        except (UnicodeError, json.JSONDecodeError):
            raise RuntimeError(f"{self.name} returned invalid JSON") from None
        try:
            choice = data["choices"][0]
            calls = choice["message"].get("tool_calls") or []
            usage = data.get("usage") or {}
            metadata = {"provider": self.name, "model": self.model, "finish_reason": choice.get("finish_reason"),
                        "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0)}
        except (KeyError, IndexError, TypeError, AttributeError):
            raise RuntimeError(f"{self.name} response has no valid completion") from None
        if any(type(metadata[k]) is not int or metadata[k] < 0 for k in ("prompt_tokens", "completion_tokens")):
            raise RuntimeError(f"{self.name} response contains invalid usage counts")
        try:
            actions = [{"name": call["function"]["name"], "arguments": json.loads(call["function"]["arguments"])} for call in calls]
            if choice.get("finish_reason") == "length" or not actions:
                raise ValueError("Missing or truncated tool calls")
        except (KeyError, TypeError, ValueError, AttributeError):
            # Malformed output is a bounded failed step, followed by fresh feedback.
            actions = []
            metadata["protocol_error"] = "Missing, malformed or truncated tool calls"
        return actions, metadata
