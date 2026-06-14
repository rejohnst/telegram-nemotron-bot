# Always-on Telegram bot → local Nemotron Super 49B on DGX Spark

A personal chatbot reachable from anywhere via Telegram, served entirely on your
DGX Spark by **NVIDIA NIM** running **Llama Nemotron Super 49B** (TensorRT-LLM,
FP4 on the GB10 Blackwell GPU).

## Why this design
- **No inbound networking.** The bot connects *outbound* to Telegram (long-polling)
  and to NIM on the internal Docker network. No port-forwarding, reverse proxy,
  HTTPS, or VPN needed — your Spark stays firewalled. Telegram is the public front door.
- **Max performance.** NIM serves the model with TensorRT-LLM, the fastest path on
  Blackwell.
- **Persistent memory.** Conversation history is stored in SQLite (a Docker volume),
  so context survives restarts and reboots.
- **Always-on.** Both services use `restart: always`.

## Architecture
```
Telegram servers ──outbound──► bot (python-telegram-bot)
                                 │  OpenAI-compatible API (internal net)
                                 ▼
                               NIM ── Nemotron Super 49B (TensorRT-LLM/FP4)
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
- `/think` — toggle Nemotron's reasoning mode (off by default: faster, direct replies).
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
- The exact NIM image tag for Nemotron Super may differ from the placeholder here;
  confirm the current tag on NGC and update `NIM_IMAGE` if needed.
- The bot image is built for the Spark's `aarch64` architecture automatically (the
  `python:3.12-slim` base is multi-arch).

## Manage
```bash
docker compose ps
docker compose restart bot
docker compose down          # stop (keeps volumes / history)
docker compose down -v       # stop and DELETE history + model cache
```
