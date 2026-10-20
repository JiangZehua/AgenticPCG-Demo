# Model providers

Ollama, LM Studio, and Portkey share one standard-library HTTP client and one verified edit pipeline. Model choice changes inference, not candidate acceptance. Both generation and optional target interpretation use the selected provider. Unity's worker reads the same repository `.env` as the CLI; no Unity-side credential or model setup is required.

## Configuration

Copy `.env.example` to `.env`. The default provider is `ollama`; model IDs are explicit and have no default. Select `ollama`, `lmstudio`, or `portkey` through `PCG_PROVIDER` or the CLI `--provider` option. Provider names are case sensitive.

Each provider uses its own `*_MODEL`, `*_BASE_URL`, and `*_API_KEY` variables. Keys from another provider are never attached to its requests. CLI flags override environment values; existing shell variables override `.env`; blank local base URLs use the defaults below. There is no automatic provider fallback, model download, or HTTP retry.

## Ollama

Install Ollama, start its local server if it is not already running, and install a model with tool-calling support:

```bash
ollama serve
# In another terminal, if a suitable model is not installed:
ollama pull llama3.1
ollama list
curl http://localhost:11434/v1/models
```

Do not start another server if the Ollama app already serves that port. Set the exact model ID shown by your installation:

```dotenv
PCG_PROVIDER=ollama
OLLAMA_MODEL=llama3.1:latest
OLLAMA_BASE_URL=http://localhost:11434/v1
```

The local server does not require an API key. `OLLAMA_API_KEY` is optional for a separately configured authenticated proxy. For local-only execution, select an installed local model rather than a cloud-backed model route. See [Ollama's OpenAI compatibility documentation](https://docs.ollama.com/api/openai-compatibility) for tools, model IDs, and context configuration.

## LM Studio

Download a tool-calling model and load it in LM Studio, then start the server from the **Developer** tab. If the `lms` CLI is installed, the equivalent commands are:

```bash
lms load YOUR_MODEL_KEY
lms server start --port 1234
curl http://localhost:1234/v1/models
```

Use the model ID returned by the server, not a filesystem path or display name:

```dotenv
PCG_PROVIDER=lmstudio
LMSTUDIO_MODEL=YOUR_LOADED_MODEL_ID
LMSTUDIO_BASE_URL=http://localhost:1234/v1
LMSTUDIO_API_KEY=
```

If server authentication is enabled, put its token in `LMSTUDIO_API_KEY`; the client sends it as `Authorization: Bearer ...`. See the official [tool-use guide](https://lmstudio.ai/docs/developer/openai-compat/tools) and [authentication guide](https://lmstudio.ai/docs/developer/core/authentication). Model/template support determines whether requests yield structured tool calls.

## Optional Portkey

Existing gateway routing remains available:

```dotenv
PCG_PROVIDER=portkey
PORTKEY_API_KEY=YOUR_KEY
PORTKEY_MODEL=YOUR_TOOL_CALLING_MODEL_ROUTE
PORTKEY_BASE_URL=https://your-gateway.example/v1
PORTKEY_VIRTUAL_KEY=
PORTKEY_CONFIG=
```

All three main Portkey fields are required. Optional virtual-key/config headers behave as before. **Migration from 0.1.0:** set `PCG_PROVIDER=portkey` explicitly; the new default is Ollama. No Portkey credentials are sent when a local provider is selected.

## CLI overrides

These flags work on both `generate` and `prepare-request --interpret`:

```bash
python3 -m unity_pcg generate --provider ollama --model llama3.1:latest \
  --base-url http://localhost:11434/v1 --model-timeout 120 \
  --request "Repair the path from player to key and exit." \
  --max-steps 4 --max-tokens 2048 --output runs/local-generation

python3 -m unity_pcg prepare-request --provider lmstudio --model YOUR_LOADED_MODEL_ID \
  --request-file request.json --output runs/prepared-local.json --interpret
```

With provider and model configured in `.env`, omit those flags. The in-game **Interpret targets** and **Generate + verify + load** buttons use that configuration on their next worker launch. Restart Play if the Unity process inherited shell variables you need to change. The request JSON schema stays provider independent.

`--model-timeout` overrides `PCG_MODEL_TIMEOUT` (default 120 seconds; allowed 1–1800). This is the per-HTTP-call wait, including cold loading; `--timeout` controls Unity physics jobs separately. The game panel also has its own overall worker deadline. Use the CLI for unusually slow runs. `--max-tokens` bounds each generation response; interpretation uses 1024 tokens. Thinking models may exhaust the budget before producing calls, so configure the model/runtime appropriately or increase the generation token budget.

## Protocol and troubleshooting

Requests use non-streaming `POST /v1/chat/completions` with function schemas. Portkey keeps `tool_choice=required`. Local requests omit forced tool selection for compatibility across runtimes and templates; the harness still requires structured tool calls. Plain prose, malformed arguments, and truncated calls are recorded as failed protocol steps, never interpreted as executable edits or proof of success. No hidden cloud retry occurs.

- **Connection failed / timeout:** start the selected server, verify its port and base URL, preload the model, or adjust `PCG_MODEL_TIMEOUT`.
- **HTTP 400 / 404:** check the exact model ID, tool support, and API base path. Use the `/v1` compatibility API, not `/api/chat` or `/api/v1/chat`.
- **HTTP 401 / 403:** configure the selected provider's credentials; LM Studio may require an API token.
- **Missing or truncated tool calls:** use a model/template with function calling and enough output/context capacity. Inspect `trace.jsonl`; a failed step retains the saved map.
- **Targets unmet:** exit code `2` means the budget ended without a verified solution. It is distinct from a server/configuration error (`1`).

Remote base URLs require HTTPS; HTTP is accepted only for `localhost`, `127.0.0.1`, and `::1`. Error messages omit server response bodies and credentials. `request.json` and trace metadata record provider and model. Token cost estimates use manually supplied prices and do not measure local hardware costs.
