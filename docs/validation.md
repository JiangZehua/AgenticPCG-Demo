# Validation

This document separates reproducible source checks from prior local evidence and unverified release gates. No standalone desktop application is certified by the current source baseline.

## Source baseline: 2026-10-20

Checks below were run on macOS arm64 with Python 3.13 and Unity 6000.6.5f1 during repository preparation. CI runs the Python suite and an installed offline demo on Python 3.10 and 3.12. CI does not run a live model or Unity.

| Check | Status | Scope |
| --- | --- | --- |
| Python unit/integration suite | Passed: 16 checks | Validation, transactions, rollback, stopping, gateway payloads/configuration, file RPC, import, UI request roundtrip |
| Offline scripted demo | Passed | Invalid deletion rejected, passage repair accepted, regression rejected; expected route 28 and hazard zones `[0,1,2]` |
| Wheel and source package | Passed | Fresh install and CLI outside the checkout; complete Unity source assets in sdist |
| Unity compilation and physics | Passed: batch Edit-mode replay | Unity 6000.6.5f1; key + win, no death, 354 physics steps, 62 colliders |
| Standalone build | Open release gate | Desktop export and independent runtime QA required |

Preparation evidence is stored locally in `runs/source-check/` and `runs/engine-check/` and excluded from Git. The wheel ran from a temporary directory outside the checkout. The source archive inventory includes the Demo scene, sprite PNGs, metadata, package manifest, and project settings, with credentials and caches excluded.

## Prior local evidence

The source project recorded local checks on 2026-10-10 and 2026-10-11. Those ignored run directories are not shipped in this repository; these notes are historical observations, not independently reproducible evidence files in the checkout.

- Python: 15 checks passed before repository preparation. Installed CLI and source-package checks passed at that time.
- Unity 6000.0.62f1: scripts compiled; an actual replay of the repaired map won with the key, no death, 354 physics steps, and 62 colliders. Sampled manual play covered movement, walls, pickup, hazard death, and winning.
- Unity 6000.6.5f1: the complete scripted accept/reject/rollback demo passed through the open Editor. The 28-step route won with the key, no death, 354 physics steps, 62 colliders, and 7.08 simulated seconds.
- Model-backed checks used a locally configured Portkey/Gemini route. A live agent run with Unity verification produced a 34-step route and a successful 432-step physics replay. This is one sample, not a reliability estimate.
- In-game target interpretation and generation loaded a verified 34-step map. Editor and runtime replay regressions passed. Model interpretation and generation were separate calls; cost was unknown.

Full manual gameplay was not repeated after the Unity upgrade. Locked-door behavior before pickup, pointer slider interaction, and the UI Cancel button lacked independent manual evidence. Stopping Play cancelled a local worker. A standalone build was never validated. Sprite-specific distribution licensing also remains open.

## Reproduce engine verification

Open `unity/` in the recorded Unity version, wait for compilation, and run from the repository root:

```bash
python3 -m unity_pcg demo --backend unity --output runs/engine-validation
```

Require `satisfied: true`, `unity.won: true`, `unity.has_key: true`, `unity.dead: false`, a positive `physics_steps`, and an exact `unity_version`. The expected backend is `unity-physics-editmode` in the Editor or `unity-physics-runtime` in Play mode. Keep trace, candidate maps, summary, and matching `.bridge/results` reports after checking them for private data.

For batch mode, close that project in the GUI and set `UNITY_EDITOR_PATH` to the Editor executable. The bridge launches a separate process for each feasible candidate. First import may need `--timeout 600`. Do not open the same project in two Editor processes.

The replay verifies one BFS route using real Rigidbody2D/collider contacts in an isolated scene. It does not certify all player policies, rendering behavior, or a complete standalone lifecycle.

## Reproduce model verification

Configure `.env` from the template, then run `generate --backend unity` with a fresh output directory. Record the request, model route and provider revision when available, budget, accepted/rejected steps, token counts, summary, and Unity report. Do not replace a failed model run with scripted actions and label it a model result.

## Manual release gates

Import the verified map, check all gameplay and UI behaviors in [the backlog](roadmap.md), build for the declared desktop target, and repeat outside the Editor. Record OS and exact Unity patch with each result. Resolve failures before changing a gate to passed.
