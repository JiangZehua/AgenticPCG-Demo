import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import sys

from .bridge import UnityBridge, atomic_json
from .harness import Harness
from .level import Level, contract, evaluate
from .provider import ModelClient, load_env


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = Path(__file__).resolve().parent / "examples"


def read_level(path):
    return Level.from_dict(json.loads(Path(path).read_text()))


def read_request(path):
    path = Path(path)
    if path.stat().st_size > 100_000:
        raise ValueError("Generation request exceeds 100 KB")
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) != {"schema_version", "domain", "instruction", "targets"}:
        raise ValueError("Request needs schema_version, domain, instruction and targets")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["domain"] != "keydoor":
        raise ValueError("Only schema_version 1 and domain keydoor are supported")
    if not isinstance(data["instruction"], str) or len(data["instruction"]) > 16_000:
        raise ValueError("Instruction must be a string of at most 16000 characters")
    return {**data, "targets": contract(data["targets"])}


def interpret_request(request, provider):
    properties = {key: {"type": "integer", "minimum": 0, "maximum": 8192}
                  for key in ("min_path_length", "max_path_length", "hazard_count")}
    properties["zone_hazards"] = {"type": "array", "minItems": 3, "maxItems": 3,
        "items": {"type": "integer", "minimum": 0, "maximum": 4096}}
    tools = [{"type": "function", "function": {"name": "set_targets",
        "description": "Return the complete executable targets for the key-door maze.",
        "parameters": {"type": "object", "properties": properties,
                       "required": ["min_path_length", "max_path_length"], "additionalProperties": False}}}]
    prompt = (
        "Translate the user's instruction into one set_targets tool call for a key-door maze. "
        "Extract ONLY explicitly requested numeric metrics; retain current defaults for unspecified metrics. "
        "Path length counts cardinal P-to-K-to-D grid steps. zone_hazards counts hazards in left/middle/right interior thirds. "
        "When total hazards change without a zone instruction, omit the old zone_hazards constraint if incompatible. "
        "If zones are specified, their sum must equal hazard_count when included. "
        "Free-form style, beauty and difficulty stay in instruction; never invent numeric metrics for them. "
        "The user will review these targets before generation. Do not edit a map."
    )
    actions, metadata = provider.propose(request, tools, 1024, system_prompt=prompt)
    if len(actions) != 1 or actions[0].get("name") != "set_targets":
        raise ValueError("Could not interpret targets; adjust controls or structured JSON instead")
    targets = contract(actions[0]["arguments"])
    return {"request": {**request, "targets": targets}, "interpretation": metadata}


def demo(output, bridge=None):
    level = read_level(EXAMPLES / "blocked.json")
    targets = contract(json.loads((EXAMPLES / "targets.json").read_text()))
    harness = Harness(level, targets, output, bridge)
    bad = harness.step([{"name": "set_tile", "arguments": {"x": 1, "y": 1, "tile": "#"}}], {"source": "scripted-demo"})
    assert not bad["accepted"] and harness.saved.digest() == level.digest()
    repaired = harness.step([{"name": "carve_corridor", "arguments": {"x1": 6, "y1": 5, "x2": 8, "y2": 5}}], {"source": "scripted-demo"})
    assert repaired["accepted"], repaired
    digest = harness.saved.digest()
    worse = harness.step([{"name": "set_tile", "arguments": {"x": 7, "y": 5, "tile": "#"}}], {"source": "scripted-demo"})
    assert not worse["accepted"] and harness.saved.digest() == digest
    summary = harness.finish("scripted_demo_complete")
    if not summary["satisfied"]:
        raise RuntimeError("Demo did not satisfy targets")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Unity Agentic PCG: generate, evaluate, import and playtest")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("demo", "generate", "evaluate"):
        sub = commands.add_parser(name)
        sub.add_argument("--output", type=Path)
        sub.add_argument("--backend", choices=("offline", "unity"), default="offline")
        sub.add_argument("--unity-project", type=Path, default=Path("unity"))
        sub.add_argument("--timeout", type=float, default=120)
        if name != "demo":
            sub.add_argument("--level", type=Path, default=EXAMPLES / "blocked.json")
            sub.add_argument("--targets", type=Path, default=EXAMPLES / "targets.json")
        if name == "generate":
            request_group = sub.add_mutually_exclusive_group(required=True)
            request_group.add_argument("--request")
            request_group.add_argument("--request-file", type=Path)
            sub.add_argument("--max-steps", type=int, default=8)
            sub.add_argument("--max-tokens", type=int, default=2048)
            sub.add_argument("--revise", action="store_true", help="Ask for at least one proposal even if the starting map meets targets")
    prepare = commands.add_parser("prepare-request", help="Validate a UI request, optionally interpret numeric targets")
    prepare.add_argument("--request-file", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--interpret", action="store_true")
    for sub in (commands.choices["generate"], prepare):
        sub.add_argument("--provider", choices=("ollama", "lmstudio", "portkey"), help="Override PCG_PROVIDER (default: ollama)")
        sub.add_argument("--model", help="Override the selected provider's model ID")
        sub.add_argument("--base-url", help="Override the selected provider's API base URL, including /v1")
        sub.add_argument("--model-timeout", type=float, help="Per-call timeout in seconds; overrides PCG_MODEL_TIMEOUT (default: 120)")
    export = commands.add_parser("export-grid", help="Convert an existing Zelda character grid to the Unity IR")
    export.add_argument("input", type=Path)
    export.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = None
    harness = None
    try:
        load_env(args.env_file)
        if args.command == "prepare-request":
            request = read_request(args.request_file)
            result = interpret_request(request, ModelClient(args.model, args.provider, args.base_url, args.model_timeout)) if args.interpret else {"request": request}
            result["controls"] = {"hazards": "hazard_count" in result["request"]["targets"],
                                  "zones": "zone_hazards" in result["request"]["targets"]}
            atomic_json(args.output, result)
            print("Targets prepared; review them before generation.")
            return 0
        if args.command == "export-grid":
            rows = args.input.read_text().splitlines()
            # Verified against both predecessors' toolusepcg/level.py ZELDA_TILE_CHARS.
            mapping = {"#": "#", ".": ".", "P": "P", "K": "K", "D": "D", "E": "H"}
            if any(c not in mapping for row in rows for c in row):
                raise ValueError("Unsupported Zelda character; expected # . P K D E")
            level = Level(["".join(mapping[c] for c in row) for row in rows])
            level.validate()
            atomic_json(args.output, level.to_dict())
            print(f"Exported {args.output}; enemies become stationary lethal hazards")
            return 0
        if not math.isfinite(args.timeout) or not 1 <= args.timeout <= 1800:
            raise ValueError("timeout must be 1..1800 seconds")
        output = args.output or Path("runs") / (args.command + "-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ValueError("Output must be a new or empty directory")
        bridge = UnityBridge(args.unity_project, args.timeout) if args.backend == "unity" else None
        if args.command == "demo":
            summary = demo(output, bridge)
        elif args.command == "evaluate":
            level = read_level(args.level)
            targets = contract(json.loads(args.targets.read_text()))
            harness = Harness(level, targets, output, bridge)
            summary = harness.finish("evaluation_complete")
        else:
            if not 1 <= args.max_steps <= 100 or not 1 <= args.max_tokens <= 16384:
                raise ValueError("max-steps must be 1..100; max-tokens must be 1..16384")
            request = read_request(args.request_file) if args.request_file else {
                "schema_version": 1, "domain": "keydoor", "instruction": args.request,
                "targets": contract(json.loads(args.targets.read_text()))}
            provider = ModelClient(args.model, args.provider, args.base_url, args.model_timeout)
            level = read_level(args.level)
            targets = request["targets"]
            atomic_json(output / "request.json", {"request": request["instruction"], "domain": request["domain"], "targets": targets, "provider": provider.name, "model": provider.model,
                        "max_steps": args.max_steps, "max_tokens": args.max_tokens, "backend": args.backend})
            harness = Harness(level, targets, output, bridge)
            summary = harness.run(provider, request["instruction"], args.max_steps, args.max_tokens, revise=args.revise)
            prices = [os.environ.get(k, "") for k in ("INPUT_USD_PER_MILLION", "OUTPUT_USD_PER_MILLION")]
            if all(prices):
                numeric = [float(p) for p in prices]
                if any(not math.isfinite(p) or p < 0 for p in numeric):
                    raise ValueError("Token prices must be finite and nonnegative")
                summary = harness.finish(summary["stop_reason"], numeric)
        print(json.dumps({"satisfied": summary["satisfied"], "backend": summary["backend"], "output": str(output.resolve()),
                          "path_length": summary["evaluation"]["path_length"], "estimated_cost_usd": summary["estimated_cost_usd"]}, ensure_ascii=False, indent=2))
        return 0 if summary["satisfied"] else 2
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        if harness is not None:
            harness.finish("execution_error")
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
