# Install & Deploy Guide

Step-by-step deployment of the always-on Telegram → Nemotron Super 49B bot on a
DGX Spark. For model swaps after install, see [`models.md`](./models.md).

---

## 1. Prerequisites (on the DGX Spark)

1. **Docker + NVIDIA Container Toolkit** — ships configured on DGX OS. Verify GPU
   access from a container:
   ```bash
   docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi
   ```
   You should see the GB10 GPU listed.

2. **NGC API key (org-scoped)** — needed to pull the NIM image.
   - Generate it at **https://org.ngc.nvidia.com/setup/api-keys** as a **Personal
     Key** with **"NGC Catalog"** included in its services.
   - A key created at `build.nvidia.com` is the same kind of key (`nvapi-…`) and
     works too — but it **must be minted while the correct org is selected** in the
     org switcher (top-left). A key from the wrong/no org logs in fine but gets
     `Access Denied` on pull (see [Troubleshooting](#access-denied-on-docker-pull)).
   - Accept the model's **governing terms** on its model card the first time:
     https://build.nvidia.com/nvidia/llama-3_3-nemotron-super-49b-v1_5

3. **Telegram bot token** — message **@BotFather** on Telegram, send `/newbot`,
   follow the prompts, and copy the token it gives you.

4. **Your Telegram user ID** (recommended, for the allowlist) — message
   **@userinfobot** on Telegram; it replies with your numeric ID.

---

## 2. Configure

```bash
cd telegram-nemotron-bot
cp .env.example .env
```

Edit `.env` and set at minimum:

```dotenv
NGC_API_KEY=<your NGC key>
TELEGRAM_BOT_TOKEN=<token from BotFather>
ALLOWED_USER_IDS=<your numeric Telegram ID>   # strongly recommended
```

> If `ALLOWED_USER_IDS` is left empty, **anyone who finds the bot can use your GPU.**
> Set it to lock the bot to yourself (comma-separate multiple IDs).

Optional tunables (sane defaults already applied): `SYSTEM_PROMPT`,
`MAX_HISTORY_TURNS`, `NIM_IMAGE`, `MODEL_NAME`.

---

## 3. Log Docker into NGC

So Docker can pull the NIM image from `nvcr.io`:

```bash
echo "$NGC_API_KEY" | docker login nvcr.io --username '$oauthtoken' --password-stdin
```

(The username is the literal string `$oauthtoken`.)

---

## 4. Launch

```bash
docker compose up -d
```

This starts two services:
- **nim** — serves Nemotron Super 49B (downloads the model and builds TensorRT
  engines on first boot; can take several minutes).
- **bot** — waits for NIM to report healthy, then connects to Telegram.

Watch progress:

```bash
docker compose logs -f nim     # wait until it reports "ready"
docker compose logs -f bot     # should show "Starting bot..."
```

When both are up, message your bot on Telegram. 🎉

---

## 5. Verify it works

- In Telegram, send your bot a message — you should get a reply.
- Commands:
  - `/start` / `/help` — usage
  - `/reset` — clear this conversation's memory
  - `/think` — toggle Nemotron's reasoning mode (off by default)

If replies fail with a model-not-found error, confirm the served model id and copy
it into `MODEL_NAME` in `.env`:

```bash
docker compose exec nim curl -s localhost:8000/v1/models
docker compose up -d bot     # re-apply .env
```

---

## 6. Switching models

The bot speaks the OpenAI API, so changing models **never touches `bot.py`** — you
edit `.env` (and, for a non-NIM backend, the compose service). Each NIM model is
cached in the `nim-cache` volume, so once built you can flip between them quickly.
See [`models.md`](./models.md) for ready-to-paste blocks and rough Spark speeds.

### Swap to another NIM model (easiest — two lines)

Edit `.env`:
```dotenv
NIM_IMAGE=nvcr.io/nim/openai/gpt-oss-120b:latest
MODEL_NAME=openai/gpt-oss-120b
```
Then rebuild/restart just the NIM service:
```bash
docker compose up -d nim                                   # pulls + builds engines
docker compose exec nim curl -s localhost:8000/v1/models   # confirm the served id
docker compose restart bot                                 # re-apply .env
```
First boot of a new model builds TensorRT engines (a few minutes); switching back to
a previously-built model is fast because it stays in `nim-cache`.

> If `MODEL_NAME` doesn't exactly match the id from `/v1/models`, replies fail with a
> model-not-found error — copy the `id` from that command into `.env`.

### Swap to a non-NIM backend (e.g. Ollama)

For models without a NIM, or to A/B against Ollama, replace the `nim` service in
`docker-compose.yml` with an `ollama` service and point the bot at it via `.env`:
```dotenv
OPENAI_BASE_URL=http://ollama:11434/v1
MODEL_NAME=gpt-oss:120b
```
The bot is unchanged — it only cares about `OPENAI_BASE_URL` + `MODEL_NAME`. Full
service block and the one-time `ollama pull` step are in [`models.md`](./models.md).

> **Reasoning-mode caveat:** the `/think` toggle uses Nemotron's `detailed thinking
> on/off` convention. It's harmless on other models but is a **no-op** on families
> that control reasoning differently (e.g. gpt-oss uses `reasoning_effort`). Normal
> chat still works out of the box; see the quirks table in `models.md`.

---

## 7. Manage / operate

```bash
docker compose ps                 # status
docker compose logs -f bot        # follow bot logs
docker compose restart bot        # restart after editing .env
docker compose pull && docker compose up -d   # update images
docker compose down               # stop (keeps history + model cache)
docker compose down -v            # stop and DELETE history + model cache
```

**Always-on:** both services use `restart: always`, so they come back automatically
after a crash or a Spark reboot (as long as the Docker daemon starts on boot, which
is the default on DGX OS).

**Persistence:** conversation history lives in SQLite on the `bot-data` volume and
survives restarts. The downloaded model + built engines live on the `nim-cache`
volume, so subsequent boots are fast.

---

## 8. Networking notes

No inbound ports, reverse proxy, VPN, or HTTPS are required. The bot connects
*outbound* to Telegram (long-polling) and to NIM on the internal Docker network, so
the Spark stays firewalled while remaining reachable from anywhere via Telegram.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `docker login` fails | Username must be the literal `$oauthtoken`; key must be a valid NGC key. |
| `docker login` **succeeds** but `docker pull` is `denied: Access Denied` | Wrong-org key or unaccepted terms — see [below](#access-denied-on-docker-pull). |
| NIM stuck "not ready" for a long time | First boot builds engines — give it several minutes; watch `docker compose logs -f nim`. |
| `402 PAYMENT_REQUIRED` pulling a model | That model is entitlement-gated on your NGC account — request access or use an Ollama backend (see `models.md`). |
| Bot replies "model not found" | `MODEL_NAME` doesn't match the served id — check `/v1/models` (step 5). |
| Bot says "Not authorized" | Your Telegram ID isn't in `ALLOWED_USER_IDS`. |
| No GPU in container | NVIDIA Container Toolkit not active — re-run the step 1 verification. |

### `Access Denied` on `docker pull`

Symptom: `docker login nvcr.io` reports **Login Succeeded**, but the pull fails with:
```
denied: {"errors": [{"code": "DENIED", "message": "Access Denied"}]}
```
Login succeeding only proves the key is *valid* — it does **not** grant access to a
specific gated NIM. Two causes, in order of likelihood:

**1. The key was generated in the wrong org (most common).**
A `build.nvidia.com` / NGC key minted with no org — or the wrong org — selected logs
in fine but has no entitlement to pull the container.
- At **https://org.ngc.nvidia.com/setup/api-keys**, switch to the **correct org**
  (org switcher, top-left) *first*, then generate a **Personal Key** with **"NGC
  Catalog"** in its services.
- Re-auth with the new key:
  ```bash
  docker logout nvcr.io
  echo "$NGC_API_KEY" | docker login nvcr.io --username '$oauthtoken' --password-stdin
  ```

**2. Governing terms not accepted.**
Open the model card and accept the license once while logged in:
https://build.nvidia.com/nvidia/llama-3_3-nemotron-super-49b-v1_5
(If "accept" silently fails to save on `build.nvidia.com`, do it from
`catalog.ngc.nvidia.com` directly or in a fresh browser session.)

**Tell which it is** — list the repo's tags with your key (a tag list ⇒ it was a
tag/path issue; denied/empty ⇒ entitlement):
```bash
API_KEY='<your nvapi- key>'
TOKEN=$(curl -s -u "\$oauthtoken:$API_KEY" \
  "https://nvcr.io/proxy_auth?scope=repository:nim/nvidia/llama-3.3-nemotron-super-49b-v1_5:pull" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://nvcr.io/v2/nim/nvidia/llama-3.3-nemotron-super-49b-v1_5/tags/list"
```
Note also that NIMs may not publish a `:latest` tag — use an exact version tag from
the [Tags tab](https://catalog.ngc.nvidia.com/orgs/nim/teams/nvidia/containers/llama-3.3-nemotron-super-49b-v1.5)
(e.g. `:1.14.0`) and set it as `NIM_IMAGE` in `.env`.
