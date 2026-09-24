# Hermes Agent with the local Nemotron NIM

This guide connects a host-installed [Hermes Agent](https://github.com/NousResearch/hermes-agent)
to the Nemotron 3.5 Lightning NIM managed by this repository on a DGX Spark.
Inference stays on the Spark. Hermes may still contact external services for
enabled tools and messaging gateways.

## Architecture

```text
Telegram ──► Hermes gateway ──► Hermes Agent and tools
                                      │
                                      │ OpenAI-compatible API
                                      ▼
                            127.0.0.1:8000
                                      │
                                      ▼
                         Nemotron 3.5 Lightning NIM
```

The Compose configuration publishes NIM as `127.0.0.1:8000:8000`. Docker
services continue to use `http://nim:8000`; the host-loopback binding lets
Hermes reach NIM without exposing inference to the LAN.

## 1. Start and verify NIM

Run these commands from this repository on the Spark:

```bash
MODEL_PRESET=model-presets/nemotron-3.5-lightning.env

./compose-model "$MODEL_PRESET" \
  -p telegram-bot up -d nim

docker compose -p telegram-bot ps
curl -sf http://127.0.0.1:8000/v1/health/ready
curl -sf http://127.0.0.1:8000/v1/models
```

The health request should report `ready`. The models response should include:

```text
nvidia/nemotron-3.5-lightning-30b-a3b
```

If NIM is still loading checkpoint shards, wait for it to become healthy before
configuring or testing Hermes.

## 2. Run the Hermes setup wizard

Install Hermes using its upstream instructions, then run its setup wizard. For
the relevant choices:

1. Choose **Blank Slate**. It installs the minimal agent while still allowing
   capabilities to be enabled later.
2. Choose **NVIDIA NIM** as the provider.
3. Finish the wizard. Some Hermes versions select the provider without asking
   for a local base URL or model; configure those explicitly in the next step.

## 3. Configure local inference

Run these commands as the same Linux user that will run Hermes and its gateway:

```bash
hermes config set NVIDIA_BASE_URL http://127.0.0.1:8000/v1
hermes config set NVIDIA_API_KEY local-nim-no-auth
hermes config set model.provider nvidia
hermes config set model.default nvidia/nemotron-3.5-lightning-30b-a3b
hermes config set model.context_length 131072
```

Local NIM does not require an inference API key. Hermes currently requires a
non-empty credential for its built-in `nvidia` provider, so
`local-nim-no-auth` is a harmless placeholder. Do not give Hermes the NGC key
used by Docker to download NIM images.

Hermes stores configuration and credentials under `~/.hermes/`. Do not add
that directory or its `.env` file to this repository.

## 4. Validate chat and tool calling

First verify a minimal inference request:

```bash
hermes -z "Reply exactly HERMES_OK"
```

Expected response:

```text
HERMES_OK
```

Then start the interactive client:

```bash
hermes
```

Use a harmless tool-call test, for example:

```text
Use the terminal to run uname -a and summarize the result.
```

Do not continue to an unattended gateway until both ordinary inference and a
basic tool call work.

## 5. Configure the Telegram gateway

Run:

```bash
hermes gateway setup
```

Recommended choices:

- Create a separate bot with BotFather. Do not reuse the token consumed by the
  `nemotron-telegram-bot` container; two long-polling clients cannot reliably
  share one Telegram bot token.
- Enter the numeric Telegram user IDs allowed to use Hermes. Do not leave the
  allowlist empty.
- Use your own account as the home channel if desired.
- Install the gateway as a system service if it should start after reboot.

Follow the service name and verification commands printed by Hermes. Service
names can vary between Hermes releases.

## 6. Security considerations

Hermes is an agent, not only a chat interface. Enabled terminal and file tools
can act with the permissions of the Linux account running Hermes.

- Keep NIM bound to `127.0.0.1`; do not change it to `0.0.0.0` without adding
  authentication and network access controls.
- Prefer a sandboxed terminal backend for untrusted tasks. A local terminal
  backend can modify files and execute commands directly on the Spark.
- Treat retrieved web pages and attachments as untrusted input because they can
  contain prompt-injection instructions.
- Restrict the Telegram gateway to explicit user IDs and protect the bot token.
- Start with a small toolset and enable additional capabilities deliberately.
- Periodically review the Hermes gateway logs, sessions, saved skills, and
  scheduled jobs.

## 7. Reboot and recovery check

The NIM service uses Docker's `restart: always`. If the Hermes gateway was
installed as a system service, both components should start automatically after
the Spark reboots. NIM may need several minutes to load before inference is
available.

After a reboot, verify:

```bash
docker compose -p telegram-bot ps
curl -sf http://127.0.0.1:8000/v1/health/ready
hermes -z "Reply exactly HERMES_OK"
```

Also check the gateway service using the exact `systemctl` or journal command
printed during `hermes gateway setup`.

## Troubleshooting

### `No usable credentials found for provider 'nvidia'`

Set the local placeholder credential and retry:

```bash
hermes config set NVIDIA_API_KEY local-nim-no-auth
```

### Connection refused on `127.0.0.1:8000`

Confirm the container is running and that Compose applied the loopback mapping:

```bash
docker compose -p telegram-bot ps
docker port nemotron-nim 8000
```

The published address should be `127.0.0.1:8000`, not `0.0.0.0:8000`.

### Model not found

Query NIM and use the exact advertised ID:

```bash
curl -sf http://127.0.0.1:8000/v1/models
```

For the preset documented here, the expected ID is
`nvidia/nemotron-3.5-lightning-30b-a3b`.

### Gateway starts before NIM is ready

The gateway can start while NIM is still loading. Wait until the NIM health
endpoint reports `ready`, then retry the Telegram message. If the gateway exits
instead of remaining available, restart its service using the command printed
by the Hermes installer.
