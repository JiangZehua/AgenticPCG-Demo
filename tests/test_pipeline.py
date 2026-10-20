"""Boundary and end-to-end checks; no test dependencies or inference needed."""

from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from unity_pcg.bridge import UnityBridge, atomic_json
from unity_pcg.cli import EXAMPLES, demo, interpret_request, main, read_level, read_request
from unity_pcg.harness import Harness
from unity_pcg.level import Level, contract, evaluate
from unity_pcg.provider import Portkey, load_env
from unity_pcg.tools import apply


REPAIR = [{"name": "carve_corridor", "arguments": {"x1": 6, "y1": 5, "x2": 8, "y2": 5}}]
TARGETS = json.loads((EXAMPLES / "targets.json").read_text())


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.level = read_level(EXAMPLES / "blocked.json")

    def test_scripted_demo_rejects_invalid_and_worse_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            result = demo(temp)
            records = [json.loads(row) for row in (Path(temp) / "trace.jsonl").read_text().splitlines()]
            self.assertEqual([r["accepted"] for r in records], [False, True, False])
            self.assertEqual(records[1]["saved_digest"], records[2]["saved_digest"])
            self.assertEqual(result["evaluation"]["path_length"], 28)
            self.assertEqual(result["evaluation"]["zone_hazards"], [0, 1, 2])
            self.assertTrue(result["satisfied"])
            self.assertEqual(result["backend"], "offline-bfs")

    def test_trust_boundaries_and_atomicity(self):
        digest = self.level.digest()
        for action in (
            {"name": "set_tile", "arguments": {"x": 0, "y": 2, "tile": "."}},
            {"name": "set_tile", "arguments": {"x": True, "y": 2, "tile": "."}},
            {"name": "set_tile", "arguments": {"x": 1, "y": 1, "tile": "."}},
            {"name": "shell", "arguments": {"command": "anything"}},
            {"name": "set_tile", "arguments": {"x": 2, "y": 2, "tile": "?"}},
            {"name": "fill_rect", "arguments": {"x1": 5, "x2": 3, "y1": 2, "y2": 3, "tile": "."}},
        ):
            with self.subTest(action=action), self.assertRaises(ValueError):
                apply(self.level, REPAIR + [action])
            self.assertEqual(self.level.digest(), digest)
        with self.assertRaises(ValueError):
            Level.from_dict({"schema_version": 1, "rows": self.level.rows, "extra": True})

    def test_high_level_tools_preserve_entities_and_moves_are_unique(self):
        filled, _ = apply(self.level, [{"name": "fill_rect", "arguments": {"x1": 1, "x2": 13, "y1": 1, "y2": 9, "tile": "."}}])
        self.assertEqual([filled.count(c) for c in "PKD"], [1, 1, 1])
        moved, _ = apply(filled, [{"name": "set_tile", "arguments": {"x": 2, "y": 2, "tile": "P"}}])
        self.assertEqual(moved.position("P"), (2, 2))
        self.assertEqual(moved.rows[1][1], ".")

    def test_door_before_key_and_hazards_are_not_walkable(self):
        level = Level(["#######", "#P.D.K#", "#######", "#H....#", "#######"])
        report = evaluate(level, {})
        self.assertFalse(report["playable"])
        self.assertIsNone(report["player_key_length"])
        self.assertEqual(report["key_door_length"], 2)
        hazards = Level(["#######", "#P.H.K#", "#######", "#D....#", "#######"])
        self.assertFalse(evaluate(hazards, {})["playable"])

    def test_contract_rejects_unsupported_and_conflicting_targets(self):
        for targets in ({"difficulty": "hard"}, {"min_path_length": True}, {"min_path_length": 10, "max_path_length": 9},
                        {"zone_hazards": [1, 2]}, {"hazard_count": 2, "zone_hazards": [0, 1, 2]}):
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                contract(targets)

    def test_unverified_finish_cannot_stop_and_budget_is_bounded(self):
        class FinishOnly:
            calls = 0
            def propose(self, observation, tools, max_tokens):
                self.calls += 1
                return [{"name": "finish", "arguments": {}}], {"prompt_tokens": 4, "completion_tokens": 2}
        provider = FinishOnly()
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            harness = Harness(self.level, TARGETS, temp)
            summary = harness.run(provider, "Connect the maze", 2)
            self.assertFalse(summary["satisfied"])
            self.assertEqual(provider.calls, 2)
            self.assertEqual(summary["stop_reason"], "step_budget_exhausted")
            self.assertEqual(summary["prompt_tokens"], 8)

    def test_engine_rejection_rolls_back_even_when_bfs_passes(self):
        class FailedPhysics:
            def evaluate(self, level, route):
                return {"won": False, "error": "Stuck at wall", "backend": "unity-physics-editmode"}
        with tempfile.TemporaryDirectory() as temp:
            harness = Harness(self.level, TARGETS, temp, FailedPhysics())
            record = harness.step(REPAIR)
            self.assertEqual(record["reason"], "unity_physics_rejected")
            self.assertEqual(harness.saved.digest(), self.level.digest())
            self.assertFalse(harness.satisfied())

    def test_agent_receives_failure_feedback_then_stops_on_verified_repair(self):
        class RepairingAgent:
            calls = 0
            def propose(self, observation, tools, max_tokens):
                self.calls += 1
                if self.calls == 1:
                    return [{"name": "set_tile", "arguments": {"x": 1, "y": 1, "tile": "#"}}], {}
                if observation["last_feedback"]["reason"] != "invalid_transaction":
                    raise AssertionError("Missing rejected-edit feedback")
                return REPAIR, {}
        provider = RepairingAgent()
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            harness = Harness(self.level, TARGETS, temp)
            summary = harness.run(provider, "Repair the map", 8)
            self.assertEqual(provider.calls, 2)
            self.assertEqual(summary["stop_reason"], "targets_met")
            self.assertTrue(summary["satisfied"])

    def test_engine_timeout_is_recorded_and_keeps_the_saved_map(self):
        class TimeoutPhysics:
            def evaluate(self, level, route):
                raise TimeoutError("Editor unavailable")
        with tempfile.TemporaryDirectory() as temp:
            harness = Harness(self.level, TARGETS, temp, TimeoutPhysics())
            with self.assertRaises(TimeoutError):
                harness.step(REPAIR)
            record = json.loads((Path(temp) / "trace.jsonl").read_text())
            self.assertEqual(record["reason"], "execution_error")
            self.assertEqual(record["saved_digest"], self.level.digest())
            self.assertEqual(harness.finish("execution_error")["stop_reason"], "execution_error")

    def test_file_bridge_correlation_and_timeout_cleanup(self):
        repaired, _ = apply(self.level, REPAIR)
        route = evaluate(repaired, TARGETS)["route"]
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "unity"
            editor = project / "Assets/AgenticPCG/Editor/AgenticBridge.cs"
            editor.parent.mkdir(parents=True)
            editor.touch()
            bridge = UnityBridge(project, timeout=2)
            for stale in (False, True):
                def responder():
                    end = time.monotonic() + 3
                    while time.monotonic() < end:
                        jobs = list((Path(temp) / ".bridge/jobs").glob("*.json"))
                        if jobs:
                            job = json.loads(jobs[0].read_text())
                            atomic_json(Path(temp) / ".bridge/results" / jobs[0].name,
                                        {"request_id": job["request_id"], "level_digest": "wrong" if stale else job["level_digest"],
                                         "backend": "unity-physics-editmode", "won": True})
                            return
                        time.sleep(.01)
                thread = threading.Thread(target=responder)
                thread.start()
                try:
                    if stale:
                        with self.assertRaises(ValueError):
                            bridge.evaluate(repaired, route)
                    else:
                        self.assertTrue(bridge.evaluate(repaired, route)["won"])
                finally:
                    thread.join()
            self.assertFalse(list((Path(temp) / ".bridge/jobs").glob("*.json")))
            bridge.timeout = .02
            with self.assertRaises(TimeoutError):
                bridge.evaluate(repaired, route)
            self.assertFalse(list((Path(temp) / ".bridge/jobs").glob("*.json")))

    def test_portkey_payload_and_malformed_tool_recovery(self):
        class Response(io.BytesIO):
            pass
        with patch.dict(os.environ, {"PORTKEY_API_KEY": "test-secret", "PORTKEY_MODEL": "@test/model", "PORTKEY_BASE_URL": "https://gateway.example/v1"}, clear=True):
            provider = Portkey()
            data = {"choices": [{"message": {"tool_calls": [{"function": {"name": "carve_corridor", "arguments": json.dumps(REPAIR[0]["arguments"])}}]},
                                 "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
            with patch("unity_pcg.provider.urlopen", return_value=Response(json.dumps(data).encode())) as request:
                actions, meta = provider.propose({"request": "Repair"}, [], 500)
                self.assertEqual(actions, REPAIR)
                self.assertEqual(meta["prompt_tokens"], 10)
                http = request.call_args.args[0]
                self.assertEqual(http.get_header("X-portkey-api-key"), "test-secret")
                self.assertNotIn("test-secret", http.data.decode())
            data["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{"
            with patch("unity_pcg.provider.urlopen", return_value=Response(json.dumps(data).encode())):
                actions, meta = provider.propose({}, [], 500)
                self.assertEqual(actions, [])
                self.assertIn("protocol_error", meta)

    def test_gateway_requires_explicit_configuration_and_secure_url(self):
        config = {"PORTKEY_API_KEY": "test-secret", "PORTKEY_MODEL": "@test/model",
                  "PORTKEY_BASE_URL": "https://gateway.example/v1"}
        for missing in config:
            with self.subTest(missing=missing), patch.dict(os.environ, {k: v for k, v in config.items() if k != missing}, clear=True):
                with self.assertRaisesRegex(ValueError, "Fill PORTKEY"):
                    Portkey()
        for url in ("http://gateway.example/v1", "https://user:secret@gateway.example/v1", "https://gateway.example/v1?key=secret"):
            with self.subTest(url=url), patch.dict(os.environ, {**config, "PORTKEY_BASE_URL": url}, clear=True):
                with self.assertRaises(ValueError):
                    Portkey()
        with patch.dict(os.environ, {**config, "PORTKEY_BASE_URL": "http://localhost:8080/v1"}, clear=True):
            self.assertEqual(Portkey().base_url, "http://localhost:8080/v1")

    def test_env_does_not_override_shell_or_expand_variables(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"PORTKEY_API_KEY": "from-shell"}, clear=True):
            path = Path(temp) / ".env"
            path.write_text('PORTKEY_API_KEY="from-file"\nPORTKEY_MODEL=@model/name\nCUSTOM_VALUE=$(no-execution)\n')
            load_env(path)
            self.assertEqual(os.environ["PORTKEY_API_KEY"], "from-shell")
            self.assertEqual(os.environ["CUSTOM_VALUE"], "$(no-execution)")

    def test_predecessor_grid_import_and_existing_output_guard(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            text = Path(temp) / "zelda.txt"
            text.write_text("\n".join(row.replace("H", "E") for row in self.level.rows))
            output = Path(temp) / "level.json"
            self.assertEqual(main(["export-grid", str(text), "--output", str(output)]), 0)
            self.assertEqual(read_level(output).to_dict(), self.level.to_dict())
            run = Path(temp) / "run"
            self.assertEqual(main(["demo", "--output", str(run)]), 0)
            before = (run / "summary.json").read_text()
            self.assertEqual(main(["demo", "--output", str(run)]), 1)
            self.assertEqual(before, (run / "summary.json").read_text())

    def test_ui_request_contract_and_cli_roundtrip(self):
        instruction = 'A winding route; keep "the key" first. Café route → exit'
        request = {"schema_version": 1, "domain": "keydoor", "instruction": instruction, "targets": TARGETS}
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            path, output = Path(temp) / "input.json", Path(temp) / "run"
            atomic_json(path, request)
            provider = unittest.mock.Mock()
            provider.model = "test-model"
            provider.propose.return_value = (REPAIR, {})
            with patch("unity_pcg.cli.Portkey", return_value=provider):
                self.assertEqual(main(["generate", "--request-file", str(path), "--output", str(output)]), 0)
            recorded = json.loads((output / "request.json").read_text())
            self.assertEqual(recorded["request"], instruction)
            self.assertEqual(recorded["targets"], TARGETS)
            for invalid in ({**request, "domain": "platformer"}, {**request, "instruction": 4},
                            {**request, "schema_version": True}, {**request, "targets": {"difficulty": 8}},
                            {**request, "extra": "ignored?"}):
                atomic_json(path, invalid)
                with self.assertRaises(ValueError):
                    read_request(path)
            atomic_json(path, {**request, "instruction": "", "targets": {}})
            prepared = Path(temp) / "prepared.json"
            self.assertEqual(main(["prepare-request", "--request-file", str(path), "--output", str(prepared)]), 0)
            self.assertEqual(json.loads(prepared.read_text())["controls"], {"hazards": False, "zones": False})

    def test_interpreted_targets_are_validated_and_revision_calls_agent(self):
        provider = unittest.mock.Mock()
        provider.propose.return_value = ([{"name": "set_targets", "arguments": {
            "min_path_length": 32, "max_path_length": 45, "hazard_count": 3, "zone_hazards": [0, 1, 2]}}], {})
        request = {"schema_version": 1, "domain": "keydoor", "instruction": "32–45 steps", "targets": TARGETS}
        resolved = interpret_request(request, provider)
        self.assertEqual(resolved["request"]["targets"]["min_path_length"], 32)
        provider.propose.return_value = ([{"name": "set_targets", "arguments": {"min_path_length": 45, "max_path_length": 32}}], {})
        with self.assertRaises(ValueError):
            interpret_request(request, provider)
        repaired, _ = apply(self.level, REPAIR)
        provider.reset_mock()
        provider.propose.return_value = ([{"name": "finish", "arguments": {}}], {})
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            harness = Harness(repaired, TARGETS, temp)
            self.assertTrue(harness.satisfied())
            summary = harness.run(provider, "Keep this map", max_steps=1, revise=True)
            self.assertEqual(provider.propose.call_count, 1)
            self.assertTrue(summary["satisfied"])


if __name__ == "__main__":
    unittest.main()
