# Changelog

## 0.1.1 — Local model providers

- Add Ollama (default) and LM Studio local tool-calling providers using their Chat Completions APIs.
- Keep Portkey as an explicit optional provider with its existing routing headers.
- Add provider, model, base URL, and per-call timeout overrides for generation and target interpretation.
- Share provider configuration with the Unity worker and record provider/model provenance.
- Isolate provider credentials and preserve bounded calls, validation, rollback, and no automatic cloud fallback.
- Document local server setup, model discovery, optional authentication, and Portkey migration.

Existing Portkey configurations must set `PCG_PROVIDER=portkey`.

## 0.1.0 — Source baseline

- Playable Unity key-door scene with a local generation panel and explicit target controls.
- Tool-using Portkey agent with bounded calls, validated map transactions, and candidate rollback.
- Offline BFS evaluation, Unity physics replay, JSON traces, and SVG previews.
- English product documentation, release checklist, and delivery acceptance criteria.
- Explicit gateway configuration without organization-specific defaults.
- Source packaging includes Unity scene, settings, sprites, and metadata.

Standalone application validation and sprite-specific distribution licensing remain open release gates. See [validation](docs/validation.md).
