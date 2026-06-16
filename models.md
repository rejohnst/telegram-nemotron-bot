# Model swap cheat-sheet (DGX Spark)

The bot speaks the OpenAI API, so swapping models never touches `bot.py` — you only
edit `.env` (and, for a non-NIM backend, the compose service). Each NIM model is
cached in the `nim-cache` volume, so once built you can flip between them quickly.

Speed note: the Spark is **memory-bandwidth bound** (273 GB/s). Dense models slow
down roughly in proportion to their size; MoE models (only a few B params active per
token) stay fast even when "large." Rough real-world chat speeds below.

**GB10/Spark essentials (apply to every NIM model here):** force eager mode
(`NIM_DISABLE_CUDA_GRAPH=1`) to dodge the sm_121 torch.compile crash; keep
`NIM_KVCACHE_PERCENT` modest (unified memory = system RAM); and enable tool calling
via `NIM_PASSTHROUGH_ARGS` with the model's parser. These are pre-set in
`docker-compose.yml` for the Nano default — adjust per model.

---

## Option N — Nemotron 3 Nano 30B-A3B (DEFAULT) — reasoning + tools, right-sized
The current default. MoE: 30B total / **~3.5B active**, so it's fast; **nvfp4 weights
are only ~21 GB**, leaving huge headroom alongside Open WebUI + SearXNG. Same Nemotron
3 generation as the Super, so it does **reasoning + tool calling together**.
```dotenv
NIM_IMAGE=nvcr.io/nim/nvidia/nemotron-3-nano:latest
MODEL_NAME=nvidia/nemotron-3-nano        # NIM serves it as plain "nemotron-3-nano"
NIM_MODEL_PROFILE=1fba9ecfcfb4cde28d4ce3fd55c40bca89a5a613e25e98f057befe6a7e99eada  # nvfp4-tp1
NIM_PASSTHROUGH_ARGS=--enable-auto-tool-choice --tool-call-parser qwen3_coder
REASONING_STYLE=nemotron3
```
Verify the profile id with `docker compose run --rm nim list-model-profiles` after any
tag bump. This is the combo that runs cleanly on the Spark today.

## Option A — Nemotron Super 49B (dense)
Best dense quality that's still responsive. ~6–10 tok/s. **Note:** tool calling
requires reasoning OFF (`detailed thinking off`) — it can't do both at once, and it
uses `REASONING_STYLE=directive`.
```dotenv
NIM_IMAGE=nvcr.io/nim/nvidia/llama-3.3-nemotron-super-49b-v1.5:latest
MODEL_NAME=nvidia/llama-3.3-nemotron-super-49b-v1.5
REASONING_STYLE=directive
```

## Option C — Nemotron 3 Super 120B-A12B (MoE) — bigger, but tight on the Spark
> ⚠️ **Caution:** this fits in memory (~60 GB nvfp4) but **OOM'd in practice** on the
> Spark once Open WebUI + SearXNG + bot were also running, even with KV caps. Workable
> if you run NIM mostly alone; otherwise prefer the Nano (Option N). Higher quality and
> still MoE-fast, but the memory margin is thin.

The newer Nemotron *3* generation, a strong pick for an **agentic** chatbot:
its NIM runs a reasoning-parser and a tool-call-parser simultaneously, so — unlike
Option A — it can **reason and call tools in the same turn** (e.g. agentic web
search in Open WebUI). MoE: 120B total but only **~12B active/token**, so it decodes
about as fast as a ~12B model despite the size. Pre-trained in **NVFP4**, loads at
~87 GB — fits the Spark's 128 GB (NVIDIA rates Spark for up to ~200B). Needs
`shm_size: 16gb` (Mamba-2 state cache) — already set on the `nim` service.

```dotenv
# Use the "-variant" tag — it's the GB10/Spark build. (The "-turbo" tag is
# datacenter H200/B200 only and ships NO GB10 profile — it will fail on the Spark
# with "0 compatible profiles".)
NIM_IMAGE=nvcr.io/nim/nvidia/nemotron-3-super-120b-a12b:1.8.0-variant
MODEL_NAME=nvidia/nemotron-3-super-120b-a12b
```
```bash
# Verify a GB10-runnable profile exists BEFORE a long pull:
docker compose run --rm nim list-model-profiles   # want GB10 (2e12:10de) under "runnable"
docker compose up -d nim                           # first boot builds engines (several min)
docker compose exec nim curl -s localhost:8000/v1/models   # confirm the served id
```
- ⚠️ **Force the nvfp4 profile.** On GB10 the image lists fp8 (~120GB) and bf16
  (~240GB) as "runnable" (NIM can't gauge unified memory), so auto-select may load
  one and OOM. Pin the ~60GB nvfp4 single-GPU profile in `.env`:
  ```dotenv
  NIM_MODEL_PROFILE=66f2cc1e52c372defe1bcf7eed8086a4c16022cefbddf2217f136f6bbcc47644
  ```
  (Re-verify the id with `docker compose run --rm nim list-model-profiles` after any
  image-tag bump.) If it still OOMs, add `NIM_KVCACHE_PERCENT=0.6` to the nim env.
- ⚠️ This tag has had reports of HTTP **400/403** downloading the `rl-030326-nvfp4`
  artifact — an NGC **entitlement/org** issue (use the org-scoped key + accept terms).
  If it won't download, use the **Ollama** fallback below (`ollama pull nemotron-3-super`).
- Confirm the current tag on the [NGC page](https://catalog.ngc.nvidia.com/orgs/nim/teams/nvidia/containers/nemotron-3-super-120b-a12b)
  and see NVIDIA's [Spark Deployment Guide](https://docs.nvidia.com/nemotron/nightly/usage-cookbook/Nemotron-3-Super/SparkDeploymentGuide/README.html).
- It loads ~87 GB, leaving ~40 GB of unified memory shared with the OS + the
  `open-webui`/`searxng`/`bot` containers + KV cache. Fits, but tighter than the 49B
  (~25 GB) — watch memory if you run long contexts alongside the web UI.
- For agentic use, no reasoning/tool tradeoff: set Open WebUI's Function Calling to
  **Native** and just use it. (Same toggle as Option A, but here reasoning can stay on.)

## Option B — gpt-oss-120B (MoE, ~5B active) — the smart "go big" pick
120B total but only ~5B active per token, so it stays fast on the Spark despite the
size. ~65 GB weights (MXFP4). Great general chat/reasoning. Like Option C, it also
does **reasoning + tool calling together** (adjustable reasoning effort), so it's a
fine agentic pick too — uses OpenAI's "harmony" format (NIM handles it).

### B1: via NIM (max performance, matches current setup)
```dotenv
NIM_IMAGE=nvcr.io/nim/openai/gpt-oss-120b:latest
MODEL_NAME=openai/gpt-oss-120b
```
```bash
docker compose up -d nim     # first boot builds engines (several min)
docker compose exec nim curl -s localhost:8000/v1/models   # confirm the served id
```
⚠️ The `nim/openai/gpt-oss-120b` image has had reports of `402 PAYMENT_REQUIRED` on
model download for some NGC accounts (entitlement-gated). If you hit that, either
request access on NGC or use the Ollama route (B2), which pulls from Ollama's library.

### B2: via Ollama (no NGC entitlement needed)
gpt-oss handling differs slightly between backends; Ollama is the no-friction path.
Replace the `nim` service in `docker-compose.yml` with:
```yaml
  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    restart: always
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    volumes:
      - ollama:/root/.ollama
    expose:
      - "11434"
    healthcheck:
      test: ["CMD", "ollama", "ps"]
      interval: 20s
      timeout: 5s
      retries: 30
      start_period: 120s
```
Add `ollama:` under the top-level `volumes:` key, point `depends_on` at `ollama`,
and set in `.env`:
```dotenv
OPENAI_BASE_URL=http://ollama:11434/v1
MODEL_NAME=gpt-oss:120b
```
Then pull the model once:
```bash
docker compose up -d ollama
docker compose exec ollama ollama pull gpt-oss:120b
docker compose up -d bot
```

---

## Other good options (drop-in `.env` blocks)

| Model | Type | NIM image / Ollama tag | `MODEL_NAME` | ~Speed |
|---|---|---|---|---|
| Llama 3.3 70B | dense | `nvcr.io/nim/meta/llama-3.3-70b-instruct:latest` | `meta/llama-3.3-70b-instruct` | ~3–5 tok/s |
| Qwen3 32B | dense | Ollama: `qwen3:32b` | `qwen3:32b` | ~8–12 tok/s |
| Gemma 3 27B | dense | Ollama: `gemma3:27b` | `gemma3:27b` | ~10–14 tok/s |
| Nemotron Super 49B | dense | (Option A above) | — | ~6–10 tok/s |
| gpt-oss-120B | MoE | (Option B above) | — | fast (MoE) |

Speeds are rough single-stream estimates; reasoning mode and long context lower them.

---

## Per-model reasoning quirks (the one model-specific bit in `bot.py`)
The bridge sends Nemotron's `detailed thinking on/off` directive and strips
`<think>…</think>`. This is harmless on other models (unknown directive ignored;
regex only fires if `<think>` appears). But each family controls reasoning differently:

- **Nemotron** — system directive `detailed thinking on/off` (already handled).
- **gpt-oss** — exposes a `reasoning_effort` param (`low`/`medium`/`high`); emits a
  separate reasoning channel rather than `<think>` tags. The `/think` toggle is a
  no-op for it, but normal chat works fine out of the box.
- **Qwen3** — `/think` and `/no_think` tokens in the prompt; uses `<think>` tags
  (so the existing stripping already cleans them up).

If you settle on a non-Nemotron model long-term, adjust the small reasoning block in
`bot.py` (`THINK_DIRECTIVE` / `_THINK_RE`, ~lines 38–42). Everything else is
model-agnostic.
