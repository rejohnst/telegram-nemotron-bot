# Install & Deploy Guide

Step-by-step deployment of the always-on Telegram → Nemotron 3 Nano 30B-A3B bot
on a DGX Spark. For model swaps after install, see [`models.md`](./models.md).

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
- **nim** — serves Nemotron 3 Nano 30B-A3B (downloads the ~21 GB nvfp4 weights on
  first boot; takes a few minutes).
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
docker compose up -d open-webui searxng
docker compose logs --tail=20 searxng     # should start clean
```
Then browse to **http://localhost:3000** (on the Spark) or **http://<spark-ip>:3000**
(from your LAN). Open WebUI auto-discovers the Nemotron model from NIM's `/v1/models`;
pick it from the model dropdown.

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

The compose file ships with Spark-appropriate defaults; this section explains them.
Context length is paid for in **KV-cache memory**, which shares the 128 GB unified
pool with the model weights (the **Nano nvfp4 default is ~21 GB**) and the other
containers. With the Nano this is comfortable; the knobs below matter most if you
swap in a much larger model (e.g. the 120B Super at ~60 GB, which is why these caps
exist — it OOM'd once the UI/search containers were also running).

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
docker compose up -d nim      # recreates NIM with the new cap
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
With the Nano (~21 GB) there's plenty of headroom, but if you run a larger model it's
safest to start NIM **alone**, confirm memory plateaus (not climbing into swap), then
add the rest:
```bash
docker compose up -d nim
watch -n 3 'free -h; echo; docker stats --no-stream'   # wait for healthy + stable
docker compose up -d open-webui searxng bot
```
If a larger model keeps fighting the memory ceiling even at low settings, drop back to
the **Nano** (the default) — it's right-sized for the Spark and runs clean.

### Eager mode + tool calling (GB10 essentials)
Two more Spark-specific settings, already wired into the `nim` service:
- `NIM_DISABLE_CUDA_GRAPH=1` → vLLM `--enforce-eager`. **Required on GB10/sm_121**:
  the torch.compile/Inductor warmup crashes otherwise (`InductorError`).
- `NIM_PASSTHROUGH_ARGS=--enable-auto-tool-choice --tool-call-parser qwen3_coder` →
  enables tool/function calling (agentic mode). Without it, agentic requests fail with
  `"auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser`. The
  Nano's tool-call parser is `qwen3_coder`.

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
| NIM crashes with `torch._inductor ... InductorError` / "Engine core initialization failed" | GB10/sm_121 torch.compile failure — set `NIM_DISABLE_CUDA_GRAPH=1` (maps to vLLM `--enforce-eager`; **not** `NIM_ENFORCE_EAGER`, which is ignored). Verify `enforce_eager: True` in the engine-args log line. Not a memory issue. |
| Agentic mode errors: `"auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser` | Tool calling not enabled on the NIM. Set `NIM_PASSTHROUGH_ARGS=--enable-auto-tool-choice --tool-call-parser qwen3_coder` on the `nim` service (Nano's parser is `qwen3_coder`), then restart nim. |
| NIM exits with "max seq len larger than KV cache can hold" | Context too large for memory — lower `NIM_MAX_MODEL_LEN` (see §10), e.g. to 65536. |
| NIM OOMs while loading | Lower `NIM_KVCACHE_PERCENT` (e.g. 0.6) and/or `NIM_MAX_MODEL_LEN` on the `nim` service; ensure the nvfp4 (not fp8/bf16) profile is forced. |
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
Note also that some NIMs may not publish a `:latest` tag — use an exact version tag
from the [Tags tab](https://catalog.ngc.nvidia.com/orgs/nim/teams/nvidia/containers/nemotron-3-nano)
and set it as `NIM_IMAGE` in `.env`. **Tip from the 120B Super:** its GB10 build was a
`-variant` tag (the `-turbo` tag was datacenter-only with no GB10 profile) — so if a
model won't show a runnable GB10 profile, check for a `-variant`-style tag.
