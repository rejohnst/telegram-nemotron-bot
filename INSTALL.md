# Install & Deploy Guide

Step-by-step deployment of the always-on Telegram → NVIDIA NIM bot on a DGX Spark.
Nemotron 3 Nano is the default; see [`models.md`](./models.md) for verified alternatives.

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
     https://build.nvidia.com/nvidia/nemotron-3-nano-30b-a3b

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

Optional tunables include `SYSTEM_PROMPT`, `MAX_HISTORY_TURNS`, `MAX_TOKENS`, and
`REASONING_BUDGET`. Prefer a file under `model-presets/` for model-specific values.

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
./compose-model model-presets/nemotron-3-nano.env up -d
```

This starts two services:
- **nim** — serves the selected NIM model and downloads/builds its profile on first
  boot.
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

If replies fail with a model-not-found error, confirm the served model ID and update
`MODEL_NAME` in the selected model preset:

```bash
docker compose exec nim curl -s localhost:8000/v1/models
./compose-model model-presets/nemotron-3-nano.env up -d bot
```

---

## 6. Switching models

The bot speaks an OpenAI-compatible API. Keep credentials and personal settings in
`.env`, then layer a model preset after it. Each NIM model is cached in the
`nim-cache` volume. See [`models.md`](./models.md) for the researched compatibility
list and the rules for validating a profile.

### Swap to another NIM model

```bash
./compose-model model-presets/gpt-oss-20b.env config --images
./compose-model model-presets/gpt-oss-20b.env up -d nim bot
docker compose exec nim curl -s localhost:8000/v1/models   # confirm the served id
```
First boot of a new model downloads assets and prepares its runtime/profile. Returning
to a cached model is faster because its assets stay in `nim-cache`.

> If `MODEL_NAME` doesn't exactly match the id from `/v1/models`, replies fail with a
> model-not-found error — copy the `id` into the selected preset and contribute the
> correction rather than adding it to personal `.env`.

### Swap to a non-NIM backend (e.g. Ollama)

For a separately managed OpenAI-compatible backend, point the bot at it via `.env`:
```dotenv
OPENAI_BASE_URL=http://ollama:11434/v1
MODEL_NAME=gpt-oss:120b
```
The Compose file now passes `OPENAI_BASE_URL` through to the bot. A backend that
replaces the `nim` service still needs its own Compose service and dependency wiring.

> **Reasoning-mode caveat:** the current bot supports Nemotron 3 and the older
> directive convention. Presets use `none` for GPT-OSS and Qwen until model adapters
> map `/think` to their controls; see [`BOT_ROADMAP.md`](./BOT_ROADMAP.md).

---

## 7. Manage / operate

```bash
docker compose ps                 # status
docker compose logs -f bot        # follow bot logs
docker compose restart bot        # restart after editing .env
./compose-model model-presets/nemotron-3-nano.env pull
./compose-model model-presets/nemotron-3-nano.env up -d
docker compose down               # stop (keeps history + model cache)
docker compose down -v            # stop and DELETE history + model cache
```

Replace the example preset above with the one currently selected whenever a command
recreates or pulls `nim` or `bot`. Plain `logs`, `ps`, `restart`, and `down` commands
do not re-resolve model environment values.

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

## 9. Optional: web chat UI + web search (Open WebUI + SearXNG)

The stack includes two optional services that hang off the same NIM model:

- **Open WebUI** — a local ChatGPT-style web UI. Streams tokens live and shows
  per-response generation stats (tokens/sec). Published on the host at port **3000**.
- **SearXNG** — a self-hosted metasearch engine that gives Open WebUI **web-search
  RAG**, so the model can answer about events after its training cutoff. Fully local,
  no API key. Internal-only (Open WebUI reaches it by container name).

### One-time setup

SearXNG needs a real secret key (the committed `searxng/settings.yml` ships with a
placeholder):
```bash
sed -i "s/CHANGE_ME_run_openssl_rand_hex_32/$(openssl rand -hex 32)/" searxng/settings.yml
```

### Start them
```bash
./compose-model model-presets/nemotron-3-nano.env --profile web up -d
docker compose logs --tail=20 searxng     # should start clean
```
Then browse to **http://localhost:3000** (on the Spark) or **http://<spark-ip>:3000**
(from your LAN). Open WebUI auto-discovers the Nemotron model from NIM's `/v1/models`;
pick the selected model from the model dropdown.

### Using web search
Web search is **off by default and toggled per chat** — it is not automatic. In a
conversation, click the **Web Search / globe toggle** in the message box, then ask a
current-events question. Open WebUI shows the sources it pulled and the model answers
from them.

### Notes
- **Speed:** injected results lengthen the prompt; since the Spark is
  memory-bandwidth-bound, responses are slower with web search on. Keep
  `WEB_SEARCH_RESULT_COUNT` small (default 3).
- **Security:** unlike the Telegram bot (outbound-only), Open WebUI opens host port
  **3000** on your LAN. It's not internet-exposed, but anyone on the network can reach
  it. `WEBUI_AUTH=False` skips login — set it to `True` if you want accounts (decide
  before first run).
- Web search here applies to **Open WebUI only**, not the Telegram bot.

### Verify SearXNG reachability
```bash
docker compose exec open-webui curl -s "http://searxng:8080/search?q=test&format=json" | head -c 300
```
JSON output = working.

---

## 10. GB10/Spark tuning (memory, context, eager mode)

The compose file ships with conservative Spark defaults. Context length is paid for
in **KV-cache memory**, which shares the 128 GB unified pool with weights, the OS,
and other containers. Exact weight/runtime use varies by image tag and selected
profile; inspect it rather than relying on parameter-count estimates.

How it works:
- The KV-cache *pool* size is set by memory utilization, not by the context length.
- `NIM_MAX_MODEL_LEN` caps the longest single sequence. At startup NIM checks that one
  sequence of that length fits in the KV pool — **if it's too large, NIM fails to
  start** ("max seq len larger than KV cache can hold").
- A smaller cap also lets the same pool serve **more concurrent requests**.
- Nemotron 3 is a hybrid Mamba-2 + attention model, so long context is cheaper here
  than on a pure transformer (Mamba state is constant-size; only attention KV grows).

### Setting it
`NIM_MAX_MODEL_LEN` is wired into the `nim` service (default **131072 = 128K**).
Override in `.env`:
```dotenv
NIM_MAX_MODEL_LEN=131072      # 128K — comfortable chatbot default
# NIM_MAX_MODEL_LEN=65536     # 64K  — frees more memory / more concurrency
# NIM_MAX_MODEL_LEN=262144    # 256K — only if you need long documents
```
```bash
./compose-model model-presets/nemotron-3-nano.env up -d nim
```

### Verify what actually loaded
Some NIM versions have ignored `NIM_MAX_MODEL_LEN`. Confirm the value took effect:
```bash
docker compose logs nim | grep -iE "max_model_len|max seq|max model length"
```
If it didn't change, fall back to a `runtime_config.json` (`{"max_model_len": 131072}`)
in the model workspace directory.

### Guidance
- Start at **128K**. It's plenty for any realistic chat or web-search RAG payload.
- Drop to **64K** if NIM struggles to start, OOMs, or you want more concurrency /
  KV headroom alongside Open WebUI + SearXNG.
- Go to **256K+** only for a genuine long-document use case, and re-check it boots.

### ⚠️ The unified-memory (UMA) runaway — read this
The single most important Spark-specific gotcha (mostly bites larger models, but the
default guards against it regardless). On a normal GPU, vLLM/NIM grabbing ~90% of "GPU
memory" for KV cache is fine. **On the Spark, "GPU memory" *is* system RAM** (unified
memory), so an unconstrained default makes NIM reserve a huge KV pool on top of the
weights → overcommit → the box fills RAM + swap and **all cores peg** on swap I/O.
Symptoms: the whole machine crawls, `free -h` shows swap full. (We hit exactly this
with the 120B Super before switching to the Nano.)

The fix is `NIM_KVCACHE_PERCENT` — the KV pool as a fraction of (unified) memory. It's
wired into the `nim` service with a safe default of **0.4**. Lower it if you still swap:
```dotenv
NIM_KVCACHE_PERCENT=0.4     # default; try 0.3 if memory is still tight
NIM_MAX_MODEL_LEN=65536     # pair with a smaller context when memory-constrained
```

If the box is already thrashing, free memory first:
```bash
docker stop nemotron-nim open-webui searxng nemotron-telegram-bot
free -h                     # used + swap should drop (a reboot is fine if wedged)
```

### Bring services up in order (matters most for large models)
With the default Nano there is ample headroom, but for a larger model it is
safest to start NIM **alone**, confirm memory plateaus (not climbing into swap), then
add the rest:
```bash
./compose-model model-presets/nemotron-3-nano.env up -d nim
watch -n 3 'free -h; echo; docker stats --no-stream'   # wait for healthy + stable
./compose-model model-presets/nemotron-3-nano.env --profile web up -d
```
If a larger model keeps fighting the memory ceiling even at low settings, drop back to
the **Nano** (the default) — it's right-sized for the Spark and runs clean.

### Model-specific engine and parser settings

`NIM_DISABLE_CUDA_GRAPH=1` maps to vLLM eager mode and works around CUDA-graph
startup failures in affected Nemotron 3 Nano releases on GB10. It is not a universal
Spark setting: the legacy Qwen3 Spark variant explicitly does not support it.

Eager mode, reasoning/tool parsers, profiles, and passthrough arguments are therefore
not global defaults. Configure them only in a model preset after checking the exact
image's NIM documentation.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `docker login` fails | Username must be the literal `$oauthtoken`; key must be a valid NGC key. |
| `docker login` **succeeds** but `docker pull` is `denied: Access Denied` | Wrong-org key or unaccepted terms — see [below](#access-denied-on-docker-pull). |
| NIM stuck "not ready" for a long time | First boot downloads assets and prepares a runtime/profile—give it several minutes and watch `docker compose logs -f nim`. |
| `402 PAYMENT_REQUIRED` pulling a model | That model is entitlement-gated on your NGC account — request access or use an Ollama backend (see `models.md`). |
| Bot replies "model not found" | `MODEL_NAME` doesn't match the served id — check `/v1/models` (step 5). |
| Bot says "Not authorized" | Your Telegram ID isn't in `ALLOWED_USER_IDS`. |
| No GPU in container | NVIDIA Container Toolkit not active — re-run the step 1 verification. |
| NIM crashes with `torch._inductor ... InductorError` / "Engine core initialization failed" | For an affected image, add `NIM_DISABLE_CUDA_GRAPH=1` to its preset and verify `enforce_eager: True`. Do not apply it to variants whose documentation marks it unsupported. |
| Agentic mode errors: `"auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser` | The selected model needs tool configuration. Add the parser documented for that exact image to its preset; do not assume another model's parser. |
| NIM exits with "max seq len larger than KV cache can hold" | Context too large for memory — lower `NIM_MAX_MODEL_LEN` (see §10), e.g. to 65536. |
| NIM OOMs while loading | Stop optional services, lower `NIM_KVCACHE_PERCENT` and/or `NIM_MAX_MODEL_LEN`, and verify that `list-model-profiles` selected a one-GB10 profile appropriate for the image. |
| Web search returns `403 Forbidden` | SearXNG JSON format not enabled — confirm `searxng/settings.yml` has the `formats:` block (incl. `json`), then `docker compose restart searxng`. |
| Web search finds nothing / times out | Check reachability with the SearXNG verify command in §9; ensure you toggled Web Search on in the chat. |

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
https://build.nvidia.com/nvidia/nemotron-3-nano-30b-a3b
(If "accept" silently fails to save on `build.nvidia.com`, do it from
`catalog.ngc.nvidia.com` directly or in a fresh browser session.)

**Tell which it is** — list the repo's tags with your key (a tag list ⇒ it was a
tag/path issue; denied/empty ⇒ entitlement):
```bash
API_KEY='<your nvapi- key>'
TOKEN=$(curl -s -u "\$oauthtoken:$API_KEY" \
  "https://nvcr.io/proxy_auth?scope=repository:nim/nvidia/nemotron-3-nano:pull" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://nvcr.io/v2/nim/nvidia/nemotron-3-nano/tags/list"
```
Do not rely on `:latest`; use an exact version tag
from the [Tags tab](https://catalog.ngc.nvidia.com/orgs/nim/teams/nvidia/containers/nemotron-3-nano)
and record it in a model preset. A `-variant` suffix often identifies a specialized
container, but the suffix alone does not prove GB10 compatibility—confirm with the
official matrix and `list-model-profiles`.
