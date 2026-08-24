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
