"""Provider configuration and real loopback HTTP integration; no models required."""

from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from unity_pcg.cli import main
from unity_pcg.provider import ModelClient


class ProviderTests(unittest.TestCase):
    def test_defaults_selection_and_provider_credentials_are_isolated(self):
        environment = {"OLLAMA_MODEL": "installed-ollama-model", "LMSTUDIO_MODEL": "loaded-studio-model",
                       "PORTKEY_MODEL": "@test/model", "PORTKEY_BASE_URL": "https://gateway.example/v1",
                       "PORTKEY_API_KEY": "portkey-secret", "PORTKEY_CONFIG": "private-route"}
        with patch.dict(os.environ, environment, clear=True):
            ollama = ModelClient()
            self.assertEqual((ollama.name, ollama.model, ollama.base_url),
                             ("ollama", "installed-ollama-model", "http://localhost:11434/v1"))
            studio = ModelClient(provider="lmstudio")
            self.assertEqual(studio.base_url, "http://localhost:1234/v1")
            for local in (ollama, studio):
                self.assertEqual(local.headers, {"Content-Type": "application/json"})
            portkey = ModelClient(provider="portkey")
            self.assertEqual(portkey.headers["x-portkey-api-key"], "portkey-secret")
            self.assertEqual(portkey.headers["x-portkey-config"], "private-route")
        with patch.dict(os.environ, {**environment, "PCG_PROVIDER": "lmstudio", "LMSTUDIO_API_KEY": "studio-token"}, clear=True):
            self.assertEqual(ModelClient().headers["Authorization"], "Bearer studio-token")
            override = ModelClient(provider="ollama", model="override", base_url="http://127.0.0.1:9999/v1/", timeout=30)
            self.assertEqual((override.model, override.base_url, override.timeout), ("override", "http://127.0.0.1:9999/v1", 30))
            self.assertNotIn("Authorization", override.headers)

    def test_invalid_configuration_fails_without_sending_requests(self):
        with patch.dict(os.environ, {}, clear=True), patch("unity_pcg.provider.urlopen") as send:
            with self.assertRaisesRegex(ValueError, "Provider must"):
                ModelClient(provider="unknown")
            for provider in ("ollama", "lmstudio"):
                with self.subTest(provider=provider), self.assertRaisesRegex(ValueError, "--model"):
                    ModelClient(provider=provider)
                for url in ("http://remote.example/v1", "https://user:secret@host/v1", "https://host/v1?key=secret", "file:///tmp/model"):
                    with self.subTest(provider=provider, url=url), self.assertRaises(ValueError):
                        ModelClient(provider=provider, model="local", base_url=url)
                for timeout in (0, 1801, float("nan"), float("inf")):
                    with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                        ModelClient(provider=provider, model="local", timeout=timeout)
            send.assert_not_called()

    def test_http_generation_and_interpretation_for_both_local_providers(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append((self.path, self.headers, payload))
                interpreting = payload["tools"][0]["function"]["name"] == "set_targets"
                name = "set_targets" if interpreting else "set_tile"
                arguments = {"min_path_length": 24, "max_path_length": 36} if interpreting else {"x": 7, "y": 5, "tile": "."}
                response = {"choices": [{"message": {"tool_calls": [{"function": {
                    "name": name, "arguments": json.dumps(arguments)}}]}, "finish_reason": "tool_calls"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
                raw = json.dumps(response).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
                "PCG_PROVIDER": "portkey", "PORTKEY_API_KEY": "do-not-send", "PORTKEY_CONFIG": "do-not-send",
                "OLLAMA_MODEL": "env-model", "LMSTUDIO_MODEL": "env-model"}, clear=True):
                base = f"http://127.0.0.1:{server.server_port}/v1"
                request = Path(temp) / "input.json"
                request.write_text(json.dumps({"schema_version": 1, "domain": "keydoor", "instruction": "Repair this maze",
                                               "targets": {"min_path_length": 24, "max_path_length": 36}}))
                for provider in ("ollama", "lmstudio"):
                    options = ["--provider", provider, "--model", "cli-model", "--base-url", base, "--model-timeout", "5"]
                    output = Path(temp) / provider
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        self.assertEqual(main(["generate", *options, "--request-file", str(request),
                                               "--max-steps", "1", "--max-tokens", "512", "--output", str(output)]), 0)
                        prepared = Path(temp) / (provider + "-prepared.json")
                        self.assertEqual(main(["prepare-request", *options, "--interpret", "--request-file", str(request),
                                               "--output", str(prepared)]), 0)
                    recorded = json.loads((output / "request.json").read_text())
                    self.assertEqual((recorded["provider"], recorded["model"]), (provider, "cli-model"))
                    summary = json.loads((output / "summary.json").read_text())
                    self.assertTrue(summary["satisfied"])
                    self.assertEqual(summary["evaluation"]["path_length"], 28)
                    trace = json.loads((output / "trace.jsonl").read_text())
                    self.assertEqual(trace["metadata"]["provider"], provider)
                    self.assertEqual(json.loads(prepared.read_text())["interpretation"]["provider"], provider)
                self.assertEqual(len(received), 4)
                for path, headers, payload in received:
                    self.assertEqual(path, "/v1/chat/completions")
                    self.assertFalse(payload["stream"])
                    self.assertNotIn("tool_choice", payload)
                    self.assertEqual(payload["model"], "cli-model")
                    self.assertNotIn("x-portkey-api-key", headers)
                    self.assertNotIn("x-portkey-config", headers)
                    self.assertNotIn("Authorization", headers)
                self.assertEqual(received[0][2]["max_tokens"], 512)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_errors_are_sanitized_and_no_cloud_retry_occurs(self):
        with patch.dict(os.environ, {}, clear=True):
            client = ModelClient(model="local", provider="ollama")
            for error in (HTTPError(client.base_url, 400, "secret-echo", {}, io.BytesIO(b"secret-body")),
                          URLError("secret-connection-details"), TimeoutError("secret-timeout")):
                with self.subTest(error=type(error).__name__), patch("unity_pcg.provider.urlopen", side_effect=error) as send:
                    with self.assertRaises(RuntimeError) as caught:
                        client.propose({}, [], 128)
                    self.assertIn("ollama", str(caught.exception))
                    self.assertNotIn("secret", str(caught.exception))
                    self.assertEqual(send.call_count, 1)
            for message in ({"content": "Success, trust me!"}, {"tool_calls": [{"function": {"name": "set_tile", "arguments": "bad-json"}}]}):
                data = {"choices": [{"message": message, "finish_reason": "stop"}]}
                with patch("unity_pcg.provider.urlopen", return_value=io.BytesIO(json.dumps(data).encode())):
                    actions, metadata = client.propose({}, [], 128)
                    self.assertEqual(actions, [])
                    self.assertIn("protocol_error", metadata)
                    self.assertEqual(metadata["prompt_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
