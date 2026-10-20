"""Verified candidate commitment, exact stopping and inspectable feedback."""

import json
from pathlib import Path
import time

from .bridge import atomic_json
from .level import evaluate
from .tools import apply, schemas


class Harness:
    def __init__(self, level, targets, output, bridge=None):
        self.saved = level
        self.targets = targets
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        if (self.output / "trace.jsonl").exists():
            raise ValueError("Output already contains a trace; choose a fresh run directory")
        self.bridge = bridge
        self.report = evaluate(level, targets)
        self.engine = None
        self.records = []
        atomic_json(self.output / "initial_level.json", level.to_dict())
        if bridge and self.report["playable"]:
            self.engine = bridge.evaluate(level, self.report["route"])

    def satisfied(self):
        return self.report["satisfied"] and (self.bridge is None or bool(self.engine and self.engine["won"]))

    def step(self, actions, metadata=None):
        started = time.monotonic()
        record = {"step": len(self.records) + 1, "actions": actions, "accepted": False,
                  "reason": "", "metadata": metadata or {}, "before_digest": self.saved.digest()}
        execution_error = None
        try:
            candidate, finish = apply(self.saved, actions)
            report = evaluate(candidate, self.targets)
            record["candidate_digest"] = candidate.digest()
            record["evaluation"] = report
            atomic_json(self.output / f"candidate_{record['step']:03d}.json", candidate.to_dict())
            if candidate.digest() == self.saved.digest():
                record["reason"] = "verified_stop" if finish and self.satisfied() else "no_change_or_unverified_stop"
            elif report["score"] > self.report["score"]:
                record["reason"] = "candidate_worsens_verified_score"
            else:
                engine = None
                if self.bridge and report["playable"]:
                    engine = self.bridge.evaluate(candidate, report["route"])
                    record["unity"] = engine
                # Geometric repairs can make partial progress, but feasible maps need engine evidence.
                if engine is not None and not engine["won"]:
                    record["reason"] = "unity_physics_rejected"
                else:
                    self.saved, self.report, self.engine = candidate, report, engine
                    record["accepted"] = True
                    record["reason"] = "verified_score_nonworsening"
        except ValueError as error:
            record["reason"] = "invalid_transaction"
            record["error"] = str(error)
        except (OSError, RuntimeError) as error:
            record["reason"] = "execution_error"
            record["error"] = str(error)
            execution_error = error
        record["seconds"] = round(time.monotonic() - started, 4)
        record["saved_digest"] = self.saved.digest()
        record["satisfied"] = self.satisfied()
        self.records.append(record)
        with (self.output / "trace.jsonl").open("a") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        if execution_error is not None:
            raise execution_error
        return record

    def run(self, provider, request, max_steps=8, max_tokens=2048, revise=False):
        for step in range(max_steps):
            if self.satisfied() and not (revise and step == 0):
                break
            observation = {"request": request, "targets": self.targets, "level": self.saved.to_dict(),
                           "evaluation": self.report, "unity": self.engine,
                           "last_feedback": self.records[-1] if self.records else None}
            actions, metadata = provider.propose(observation, schemas(self.saved), max_tokens)
            record = self.step(actions, metadata)
            print(f"Step {record['step']}: {record['reason']} | score={self.report['score']}", flush=True)
        return self.finish("targets_met" if self.satisfied() else "step_budget_exhausted")

    def finish(self, stop_reason, prices=None):
        summary = {"schema_version": 1, "protocol": "unity-keydoor-v1", "stop_reason": stop_reason,
                   "backend": (self.engine or {}).get("backend", "unity-physics") if self.bridge else "offline-bfs",
                   "satisfied": self.satisfied(), "targets": self.targets, "evaluation": self.report,
                   "unity": self.engine, "steps": len(self.records),
                   "accepted_steps": sum(r["accepted"] for r in self.records),
                   "prompt_tokens": sum(r["metadata"].get("prompt_tokens", 0) for r in self.records),
                   "completion_tokens": sum(r["metadata"].get("completion_tokens", 0) for r in self.records),
                   "estimated_cost_usd": None}
        if prices is not None:
            summary["estimated_cost_usd"] = (summary["prompt_tokens"] * prices[0] + summary["completion_tokens"] * prices[1]) / 1_000_000
        atomic_json(self.output / "final_level.json", self.saved.to_dict())
        atomic_json(self.output / "summary.json", summary)
        render_svg(self.saved, self.report["route"], self.output / "level.svg")
        return summary


def render_svg(level, route, path):
    colors = {"#": "#334155", ".": "#e2e8f0", "P": "#38bdf8", "K": "#fbbf24", "D": "#34d399", "H": "#f87171"}
    cells = []
    for y, row in enumerate(level.rows):
        for x, tile in enumerate(row):
            cells.append(f'<rect x="{x * 32}" y="{y * 32}" width="31" height="31" rx="3" fill="{colors[tile]}"/>')
            if tile in "PKDH":
                cells.append(f'<text x="{x * 32 + 16}" y="{y * 32 + 22}" text-anchor="middle" fill="#0f172a" font-family="sans-serif" font-size="19">{tile}</text>')
    points = " ".join(f"{p['x'] * 32 + 16},{p['y'] * 32 + 16}" for p in route)
    Path(path).write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {level.width * 32} {level.height * 32}" role="img" aria-label="Key-door level with verified BFS route">' +
                         "".join(cells) + f'<polyline points="{points}" fill="none" stroke="#6366f1" stroke-width="3" opacity=".65"/></svg>\n')
