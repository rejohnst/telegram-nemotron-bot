# Always-on Telegram bot → local Nemotron 3 Nano on DGX Spark

A personal chatbot reachable from anywhere via Telegram, served entirely on your
DGX Spark by **NVIDIA NIM** running **Nemotron 3 Nano 30B-A3B** (an MoE model —
30B total / ~3.5B active — that does reasoning *and* tool calling together; NVFP4,
~21 GB, right-sized for the Spark's GB10). Larger models (Nemotron 3 Super 120B,
gpt-oss-120B, the older Nemotron Super 49B) are drop-in swaps — see
[`models.md`](./models.md). Note: the 120B Super fits in memory but OOM'd in practice
once the UI/search containers were also running; the Nano is the comfortable default.

## Why this design
- **No inbound networking.** The bot connects *outbound* to Telegram (long-polling)
  and to NIM on the internal Docker network. No port-forwarding, reverse proxy,
  HTTPS, or VPN needed — your Spark stays firewalled. Telegram is the public front door.
- **Local & private.** NIM serves the model via its vLLM backend on the GB10 (eager
  mode — see the GB10 notes below), exposing an OpenAI-compatible API. Nothing leaves
  the box except outbound Telegram polling.
- **Persistent memory.** Conversation history is stored in SQLite (a Docker volume),
  so context survives restarts and reboots.
- **Always-on.** Both services use `restart: always`.

## Architecture
```
Telegram servers ──outbound──► bot (python-telegram-bot)
                                 │  OpenAI-compatible API (internal net)
                                 ▼
                               NIM ── Nemotron 3 Nano 30B-A3B (vLLM/NVFP4, GB10)
```

## Prerequisites (on the DGX Spark)
1. Docker + the NVIDIA Container Toolkit (ships configured on DGX OS).
   Verify GPU access: `docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi`
2. An **NGC account + API key** — https://ngc.nvidia.com → *Setup → Generate API Key*.
3. A **Telegram bot token** — message **@BotFather**, `/newbot`, copy the token.
4. Your **Telegram user ID** (recommended, for the allowlist) — message **@userinfobot**.

## Setup
```bash
cd telegram-nemotron-bot
cp .env.example .env
# edit .env: set NGC_API_KEY, TELEGRAM_BOT_TOKEN, and ALLOWED_USER_IDS

# Log Docker into NGC so it can pull the NIM image:
echo "$NGC_API_KEY" | docker login nvcr.io --username '$oauthtoken' --password-stdin

docker compose up -d
```

First boot downloads the model and builds TensorRT engines — this can take several
minutes. Watch progress:
```bash
docker compose logs -f nim    # wait for "ready"
docker compose logs -f bot
```
Then message your bot on Telegram. 🎉

## Using it
- Just chat normally.
- `/reset` — clear this conversation's memory.
- `/think` — toggle the model's reasoning mode (Nemotron 3 reasons by default).
- `/help` — show commands.

## Common tweaks
- **Persona / behavior:** set `SYSTEM_PROMPT` in `.env`.
- **Context length:** `MAX_HISTORY_TURNS` (turns of history sent each request).
- **Lock down access:** set `ALLOWED_USER_IDS` (comma-separated). If empty, anyone
  who discovers the bot can use your GPU.
- **Different/newer model:** change `NIM_IMAGE` and `MODEL_NAME` together.

## Notes & gotchas
- `MODEL_NAME` must exactly match the model id the NIM advertises. If replies fail
  with a model-not-found error, check `curl http://localhost:8000/v1/models` from
  inside the nim container (`docker compose exec nim curl -s localhost:8000/v1/models`)
  and copy the `id` into `.env`.
- The exact NIM image tag may differ from the default here; confirm the current tag
  on NGC and update `NIM_IMAGE` if needed.
- Switching models also means setting `REASONING_STYLE` to match the model's
  reasoning convention (`nemotron3` / `directive` / `none`) — see `models.md`.
- The bot image is built for the Spark's `aarch64` architecture automatically (the
  `python:3.12-slim` base is multi-arch).
- **GB10/Spark specifics** (all pre-set in `docker-compose.yml`, detailed in
  `INSTALL.md` §10): use the GB10 NIM build + a pinned **nvfp4** profile; force eager
  mode (`NIM_DISABLE_CUDA_GRAPH=1`) to dodge the sm_121 torch.compile crash; cap
  KV-cache (`NIM_KVCACHE_PERCENT`) since unified memory = system RAM; and enable tool
  calling via `NIM_PASSTHROUGH_ARGS=--enable-auto-tool-choice --tool-call-parser qwen3_coder`.

## Manage
```bash
docker compose ps
docker compose restart bot
docker compose down          # stop (keeps volumes / history)
docker compose down -v       # stop and DELETE history + model cache
```
