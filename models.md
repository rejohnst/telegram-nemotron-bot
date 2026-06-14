# Model swap cheat-sheet (DGX Spark)

The bot speaks the OpenAI API, so swapping models never touches `bot.py` — you only
edit `.env` (and, for a non-NIM backend, the compose service). Each NIM model is
cached in the `nim-cache` volume, so once built you can flip between them quickly.

Speed note: the Spark is **memory-bandwidth bound** (273 GB/s). Dense models slow
down roughly in proportion to their size; MoE models (only a few B params active per
token) stay fast even when "large." Rough real-world chat speeds below.

---

## Option A — Nemotron Super 49B (default, dense)
Best dense quality that's still responsive. ~6–10 tok/s.
```dotenv
NIM_IMAGE=nvcr.io/nim/nvidia/llama-3.3-nemotron-super-49b-v1.5:latest
MODEL_NAME=nvidia/llama-3.3-nemotron-super-49b-v1.5
```

## Option B — gpt-oss-120B (MoE, ~5B active) — the smart "go big" pick
120B total but only ~5B active per token, so it stays fast on the Spark despite the
size. ~65 GB weights (MXFP4). Great general chat/reasoning.

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
