# Always-on Telegram bot → local NVIDIA NIM on DGX Spark

A personal chatbot reachable from anywhere via Telegram, served entirely on your
DGX Spark by **NVIDIA NIM**. The default is **Nemotron 3 Nano 30B-A3B**, while
versioned presets also cover other NVIDIA-verified single-Spark models. See
[`models.md`](./models.md) for the researched shortlist and switching workflow.

## Why this design
- **No inbound networking.** The bot connects *outbound* to Telegram (long-polling)
  and to NIM on the internal Docker network. No port-forwarding, reverse proxy,
  HTTPS, or VPN needed — your Spark stays firewalled. Telegram is the public front door.
- **Local inference.** NIM exposes an OpenAI-compatible API only on the internal
  Compose network. Telegram messages still pass through Telegram's service, but
  prompts are not sent to a hosted model provider.
- **Persistent memory.** Conversation history is stored in SQLite (a Docker volume),
  so context survives restarts and reboots.
- **Always-on.** Both services use `restart: always`.

## Architecture
```
Telegram servers ──outbound──► bot (python-telegram-bot)
                                 │  OpenAI-compatible API (internal net)
                                 ▼
                               NIM ── selected model preset (GB10)
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

./compose-model model-presets/nemotron-3-nano.env up -d
```

First boot downloads model assets and prepares the selected runtime/profile; this can
take several minutes. Watch progress:
```bash
docker compose logs -f nim    # wait for "ready"
docker compose logs -f bot
```
Then message your bot on Telegram. 🎉

## Using it
- Just chat normally.
- `/reset` — clear this conversation's memory.
- `/think` — toggle supported reasoning modes (off by default).
- `/help` — show commands.

## Common tweaks
- **Persona / behavior:** set `SYSTEM_PROMPT` in `.env`.
- **Context length:** `MAX_HISTORY_TURNS` (turns of history sent each request).
- **Lock down access:** set `ALLOWED_USER_IDS` (comma-separated). If empty, anyone
  who discovers the bot can use your GPU.
- **Different model:** layer a versioned file from `model-presets/`; see
  [`models.md`](./models.md) and the `compose-model` wrapper.

## Notes & gotchas
- `MODEL_NAME` must exactly match the model id the NIM advertises. If replies fail
  with a model-not-found error, check `curl http://localhost:8000/v1/models` from
  inside the nim container (`docker compose exec nim curl -s localhost:8000/v1/models`)
  and copy the `id` into the selected model preset.
- Image tags, profile hashes, served IDs, and tool parsers are model-specific. Verify
  them with `list-model-profiles` and `/v1/models` after any image-tag change.
- Switching models also means setting `REASONING_STYLE` to match the model's
  reasoning convention (`nemotron3` / `directive` / `none`) — see `models.md`.
- The bot image is built for the Spark's `aarch64` architecture automatically (the
  `python:3.12-slim` base is multi-arch).
- **GB10/Spark specifics** are detailed in `INSTALL.md` §10. Shared defaults
  conservatively cap KV-cache use; presets carry model-specific eager-mode,
  reasoning-parser, and profile settings.

## Planned bot enhancements

The staged plan for streaming, safe splitting, attachments, tools/search, per-chat
controls, observability, and resilient error handling is in
[`BOT_ROADMAP.md`](./BOT_ROADMAP.md).

## Manage
```bash
docker compose ps
docker compose restart bot
docker compose down          # stop (keeps volumes / history)
docker compose down -v       # stop and DELETE history + model cache
```

Use the same `compose-model` preset whenever recreating or pulling the NIM service.
