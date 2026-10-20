# Contributing

Treat changes as deliverable software: a fresh checkout must run, behavior must be verifiable, and documentation must describe the implementation that ships. Keep code, comments, examples, UI labels, and documentation in English.

## Development

Use Python 3.10+ and Unity 6000.6.5f1. The Python runtime uses only the standard library. Open `unity/` as the Unity project; run Python commands from the repository root.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
python -m unity_pcg demo --output runs/development-check
```

Use a fresh output directory for each run. Model-backed work needs your own `.env`; use `.env.example` as its template. Never commit credentials, `.bridge`, local run logs, Unity caches, or recovery scenes. Commit Unity `.meta` files with their assets.

## Change expectations

- Keep pull requests focused on one behavior or release gate. Describe the problem, resulting behavior, and validation.
- Exercise changed behavior at the appropriate boundary. Offline checks cover Python contracts; physics changes need an actual Unity report; player/UI changes need Play-mode checks.
- Preserve candidate rollback, strict request validation, bounded calls, and evaluator-controlled success.
- Keep documentation and validation claims consistent with observed results. Record exact Unity version and backend for engine evidence.
- Check sanitized run artifacts before attaching them: instructions and local paths can contain private information.

## Delivery handoff

The [delivery backlog](docs/roadmap.md) lists concrete remaining work. For each completed item, provide the source change, reproduction command, observed result, and remaining limitation. Use pull requests for review; publishing release packages follows the [release checklist](docs/release.md).
