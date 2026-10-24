# Nemotron 3.5 Bolt 74B-A9B 24GB on DGX Spark

Research/configuration checked on 2026-10-23. This integration has **not yet been
run on the target Spark**; validate startup, chat, `/think`, and tool calls before
replacing a working Lightning deployment permanently.

## Runtime and scope

NVIDIA's [native 24GB model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB)
documents a vLLM recipe supporting Blackwell SM120/SM121. A model-specific NIM
image could not be verified for this release. This preset therefore builds a
vLLM server; it does not invent a NIM image or reuse Lightning's profile hash.
The native checkpoint is distinct from the separately published GGUF variant.

`compose-model` selects `docker-compose.bolt.yml` automatically for this preset.
It replaces the `nim` service runtime while preserving its service/container
names, GPU reservation, restart policy, client dependencies, and endpoints:

- Docker clients: `http://nim:8000/v1`
- Hermes on the Spark: `http://127.0.0.1:8000/v1`
- Model ID: `nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB`

The image is based on the vLLM revision NVIDIA specifies, pinned by manifest
digest (verified to include Linux ARM64), plus `b12x==1.5.1`. Model weights,
remote model code, and the `ultra_v3` reasoning plugin use a pinned Hugging Face
revision. `--trust-remote-code` is required by the recipe: starting this preset
executes that model repository's Python code. Review it before deployment.

Initial settings use 131,072 context tokens, one concurrent sequence and a GPU
memory utilization ceiling of 0.5 to leave unified-memory headroom for the OS
and other services. The 24GB label is the model's packed-memory target, not a
cap on total server RAM or download size. These settings need Spark measurement.
Speculative decoding is omitted initially; NVIDIA's optional LiLiCorr drafter
can be evaluated after the basic server works.

The existing Telegram bridge remains text-only and supports `/think` through
`chat_template_kwargs.enable_thinking`. Open WebUI/Hermes can use the server's
native tool calling. Model vision support does not add Telegram attachments or
tool execution to the bridge.

## Deploy on DGX Spark

Prerequisites: the existing `.env`, NVIDIA Container Toolkit, and Docker Compose
2.24.4 or newer (`!override` support). No NGC credentials are forwarded to Bolt;
`HF_TOKEN` in `.env` is optional for authenticated Hugging Face downloads.

Run from this repository, keeping the existing project name to retain volumes:

```bash
MODEL_PRESET=model-presets/nemotron-3.5-bolt.env
./compose-model "$MODEL_PRESET" -p telegram-bot --profile web config --quiet
./compose-model "$MODEL_PRESET" -p telegram-bot config --images
./compose-model "$MODEL_PRESET" -p telegram-bot build nim
```

This builds on the Spark's ARM64 CPU; it does not download all model weights at
build time. Kernel preparation and model download happen on first startup.

Stop clients and the old inference process before loading Bolt. Do not run two
model servers simultaneously while evaluating memory use:

```bash
./compose-model "$MODEL_PRESET" -p telegram-bot --profile web stop bot open-webui nim
./compose-model "$MODEL_PRESET" -p telegram-bot up -d nim
./compose-model "$MODEL_PRESET" -p telegram-bot logs --tail=100 -f nim
```

Use Ctrl+C to leave the logs (the container keeps running). When ready:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/v1/models
curl -fsS http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB","messages":[{"role":"user","content":"Reply exactly BOLT_OK"}],"max_tokens":128,"chat_template_kwargs":{"enable_thinking":false}}'

./compose-model "$MODEL_PRESET" -p telegram-bot --profile web up -d bot open-webui searxng
```

Verify a Telegram reply and `/think` on/off. Check system RAM and swap during
startup and a long response. A separate `bolt-cache` volume retains Hugging Face
assets; the original `nim-cache`, bot database, and WebUI volume are preserved.
The old container name `nemotron-nim` is retained even though it now runs vLLM.
`list-model-profiles` and `/v1/health/ready` are NIM-only; Bolt uses `/health`.

For settings in the root `.env`, Bolt supports `BOLT_MAX_MODEL_LEN` (default
131072) and `BOLT_GPU_MEMORY_UTILIZATION` (default 0.5). NIM memory/profile/parser
variables are not forwarded. `MAX_TOKENS=16384` in the preset allows thinking
and the final answer to share a larger completion budget.

## Hermes

Keep the endpoint and placeholder credential from [HERMES.md](./HERMES.md).
Change the model and retain the matching context length:

```bash
hermes config set model.default nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB
hermes config set model.context_length 131072
hermes -z "Reply exactly HERMES_OK"
hermes gateway restart
```

Clear any chat-specific model override and start a new Telegram session. Test a
harmless tool call as well as ordinary chat. The endpoint speaks the same
OpenAI-compatible chat API; Hermes' NVIDIA provider credential remains a local
placeholder. Match Hermes' context setting if you change the server cap.

## Restart and rollback

After a reboot Docker should restart this container. For any Compose operation
that creates/recreates services, use the Bolt preset and wrapper again. Plain
`docker compose up` resolves the default NIM configuration instead.

To restore Lightning, stop Bolt before starting the prior server:

```bash
./compose-model model-presets/nemotron-3.5-bolt.env -p telegram-bot --profile web stop bot open-webui nim
./compose-model model-presets/nemotron-3.5-lightning.env -p telegram-bot up -d nim
```

Wait for `http://127.0.0.1:8000/v1/health/ready`, then:

```bash
./compose-model model-presets/nemotron-3.5-lightning.env -p telegram-bot --profile web up -d bot open-webui searxng
hermes config set model.default nvidia/nemotron-3.5-lightning-30b-a3b
hermes gateway restart
```

Never use `down -v` to switch models: it deletes persistent data and caches.

