# Model presets

Each file contains only model-specific settings. Keep credentials and personal bot
settings in the root `.env`, then layer one preset after it:

```bash
./compose-model model-presets/gpt-oss-20b.env up -d nim bot
```

The last env file wins. Always check the selected image before pulling and verify
the API model ID after startup:

```bash
./compose-model model-presets/gpt-oss-20b.env config --images
docker compose exec nim curl -s localhost:8000/v1/models
```

Tags and served model IDs can change between NIM releases. Update a preset only
after `list-model-profiles` reports a runnable one-GPU GB10 profile and `/v1/models`
confirms the ID.

`nemotron-3-nano.env` pins the TP1 NVFP4 profile observed on the target GB10 with
NIM 2.0.8 on 2026-08-24. Profile hashes and parser support are image-specific, so
repeat that check before changing its image tag. Nemotron presets also enable the
documented reasoning and automatic tool-call parsers; those flags intentionally do
not leak into unrelated model presets.
