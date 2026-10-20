# Delivery backlog

The baseline is a working source demo: offline repair, a playable embedded map, model-driven edits, and optional Unity verification. The next milestone is a reproducible desktop release. Complete the following work in priority order and attach evidence to the corresponding pull request.

| Priority | Deliverable | Acceptance criteria |
| --- | --- | --- |
| P0 | Fresh-checkout verification | Install on a clean environment, pass all Python checks and the offline demo, import the Unity project without compile errors, and record exact versions. |
| P0 | Unity gameplay regression | Verify movement, wall blocking, door blocking before key pickup, pickup, winning, hazard death, and restart. Attach an actual physics replay report and a short capture of manual play. |
| P0 | Desktop application | Build one declared desktop target, launch it outside the Editor, and repeat gameplay checks. Document OS, Unity version, launch steps, and the build artifact. |
| P0 | Sprite licensing | Establish per-file distribution permission for all six reused sprites or replace them with assets having confirmed licensing; update attribution. |
| P1 | Generation handoff | Configure each advertised provider from the template, run model-backed generation with Unity verification, and retain sanitized request, trace, summary, candidates, token usage, and backend/version. |
| P1 | UI lifecycle regression | Exercise prompt/JSON modes, target preparation, pointer sliders, keyboard focus, Cancel, timeout, invalid requests, and exiting Play during a worker. Failed/cancelled runs must preserve the displayed map. |
| P1 | Standalone generation setup | Decide whether the desktop release includes generation. If included, document and verify Python/repository discovery, provider configuration, cancellation, and physics replay outside the Editor. Otherwise clearly scope the binary to embedded-map play. |
| P1 | Release bundle | Produce source archive, Python wheel, sanitized offline example, desktop artifact, and release notes. Verify each from its documented entry point. |

## Definition of done

A deliverable includes working source, English documentation, a reproducible check, and observed evidence. A successful offline test is not engine evidence; a physics report does not replace manual gameplay or a standalone build. Update [validation.md](validation.md) when a gate is verified.

Additional domains, new rendering styles, and agent search strategies are outside the initial desktop milestone. Preserve the current `keydoor` contract while closing the release gates.
