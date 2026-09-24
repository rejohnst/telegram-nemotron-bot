# NIM model selection on DGX Spark

Research checked against NVIDIA's NGC catalog and NIM support matrices on
**2026-08-24**. Treat compatibility as a property of the complete
**image tag + model profile + GPU** combination, not just the model name.

## Recommended single-Spark choices

| Model | Why choose it | Verified Spark status | Caveats |
|---|---|---|---|
| Nemotron 3 Nano 30B-A3B | Current balanced default; fast MoE, reasoning and tools | NIM 2.0.8 reported runnable TP1 BF16, FP8, and NVFP4 profiles on the target GB10; the preset pins the 21 GB NVFP4 profile | Profile hash is tied to the pinned image tag |
| Nemotron 3.5 Lightning 30B-A3B | Best candidate for the next default; 3B active parameters, reasoning, agents, coding, 1M model context | Current matrix verifies GB10 and lists a 30 GB TP1 NVFP4 floor | Early-access container as of this review; benchmark before promoting |
| GPT-OSS 20B | Strong compact reasoning and tool-use option | Current matrix explicitly verifies GB10 with TP1 MXFP4 | `/think` needs a `reasoning_effort` adapter |
| Qwen3 32B for DGX Spark | Multilingual, reasoning and agent use; dedicated NVFP4 build | Spark-only NIM profile, one GB10, about 41.6 GB disk footprint | Legacy 1.x variant; `/think` needs Qwen controls |
| Nemotron Nano 9B v2 for DGX Spark | Low memory use and NVIDIA reasoning/tool support | Dedicated one-Spark container | Lower quality ceiling than the 30B MoE choices |
| Llama 3.1 8B Instruct for DGX Spark | Fast, simple, predictable chat/summarization baseline | Dedicated one-Spark FP8 container | No native reasoning mode; older model |

The corresponding ready-to-layer files live in [`model-presets/`](./model-presets/).

## Switching models

Keep secrets and personal settings in `.env`. Layer the selected model preset last:

```bash
./compose-model model-presets/qwen3-32b-spark.env up -d nim bot
```

Before a large pull, inspect the resolved image:

```bash
./compose-model model-presets/qwen3-32b-spark.env config --images
```

Then verify both hardware compatibility and the served API ID:

```bash
./compose-model model-presets/qwen3-32b-spark.env run --rm nim list-model-profiles
docker compose exec nim curl -s localhost:8000/v1/models
```

If `/v1/models` advertises a different ID, update `MODEL_NAME` in that preset. Never
reuse `NIM_MODEL_PROFILE` or a tool-call parser across models without verifying it;
both are image/model-specific.

## Generic model support: two levels

1. **Optimized model-specific NIMs (recommended):** swap `NIM_IMAGE`, `MODEL_NAME`,
   reasoning style, and sampling through a preset. These containers give the most
   predictable performance and are curated by NVIDIA.
2. **Model-Free NIM (future extension):** use `nvidia/model-free-nim` with
   `NIM_MODEL_NAME` pointing to an NGC, Hugging Face, or local model. NVIDIA now
   verifies the container itself on GB10, but each selected model must still fit and
   be supported by its bundled backend. External model code and weights require a
   separate supply-chain review.

The current Compose file exposes `NIM_MODEL_NAME`, `NIM_SERVED_MODEL_NAME`, and
`HF_TOKEN` so a model-free preset can be added later. It intentionally does not ship
one yet: picking a default third-party model and trust policy is a separate decision.

## Models not recommended for this one-Spark stack

- **Nemotron 3 Super 120B-A12B:** the repo's earlier experiment loaded only under a
  narrow NVFP4 configuration and then ran out of unified-memory headroom alongside
  the UI/search containers. The current NIM 2.x support matrix does not list GB10 as
  a verified GPU for this model. Treat it as experimental, not plug-and-play.
- **GPT-OSS 120B:** the current NIM 2.x matrix does not list GB10 among its verified
  GPUs. Prefer GPT-OSS 20B here.
- **MiniMax M2.5 and DeepSeek V4 Flash:** NVIDIA's Spark deployment guide requires
  two DGX Spark systems for these large profiles.
- Generic 70B dense models may fit at low precision, but fitting in 128 GB unified
  memory does not establish an optimized or supported one-Spark NIM profile.

## Operational rules

- Pin exact image tags in presets; do not make `latest` part of a reproducible setup.
- Run `list-model-profiles` after every tag change. Profile hashes are not stable API;
  the Nano preset's pinned hash was verified only with NIM 2.0.8 on the target Spark.
- Keep engine flags and reasoning/tool parsers in presets. The Nemotron presets use
  `nemotron_v3` reasoning plus `qwen3_coder` automatic tool calling, while the Qwen3
  Spark variant does not support the eager-mode environment variable.
- Start NIM alone after a model change and watch system RAM/swap before adding UI
  services.
- Keep `NIM_KVCACHE_PERCENT` conservative on unified memory and lower
  `NIM_MAX_MODEL_LEN` when startup or concurrency needs more headroom.
- The model's advertised maximum context is not a safe default allocation.

## Official sources

- [Current NIM LLM support matrix](https://docs.nvidia.com/nim/large-language-models/latest/reference/support-matrix.html)
- [NIM 1.15 model-specific catalog and legacy Spark variants](https://docs.nvidia.com/nim/large-language-models/1.15.0/models.html)
- [DGX Spark collection in NGC](https://catalog.ngc.nvidia.com/orgs/nvidia/-/collections/dgx-spark/-/)
- [NIM model-specific versus multi/model-free overview](https://docs.nvidia.com/nim/large-language-models/1.15.0/introduction.html)
- [NIM configuration reference](https://docs.nvidia.com/nim/large-language-models/1.15.0/configuration.html)
- [Nemotron 3.5 Lightning NIM launch settings](https://docs.nvidia.com/nim/large-language-models/2.0.10/get-started/advanced/get-started-nemotron-3.5-lightning.html)
- [Legacy Spark variant behavior and limitations](https://docs.nvidia.com/nim/large-language-models/1.15.0/nim-container-variants.html)
- [Two-node DGX Spark deployment guide](https://docs.nvidia.com/nim/large-language-models/1.15.0/deploy-on-dgx-spark.html)
