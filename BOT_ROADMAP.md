# Telegram bot enhancement plan

The work is ordered to establish reliable request/response primitives before adding
tools and multimodal inputs. Each phase should include unit tests and an integration
test against a fake OpenAI-compatible server.

## Phase 0 — foundations and testability

- Split `bot.py` into configuration, persistence, model client, Telegram formatting,
  and handlers without changing behavior.
- Validate configuration at startup with actionable errors (token, numeric ranges,
  reasoning style, database path, backend URL).
- Add pytest coverage for history, reasoning request construction, authorization,
  formatting, and configuration.
- Add Ruff/type checking and a small CI workflow; add dependency update policy.
- Introduce a model capability object (`reasoning`, `tools`, `vision`, `audio`,
  context/output limits) populated by each model preset.

Exit criterion: behavior is covered by tests and model-specific conditionals no
longer spread through Telegram handlers.

## Phase 1 — streaming and Telegram-safe rendering

- Request streaming completions and periodically edit a placeholder Telegram message
  rather than sending one message per token.
- Coalesce updates by time and character thresholds to stay below Telegram rate
  limits; fall back to a final non-streaming send if editing fails.
- Replace fixed Python slicing with a splitter that counts Telegram UTF-16 code units,
  prefers paragraph/line/word boundaries, preserves code fences, and guarantees that
  every chunk is within 4096 units.
- Define formatting behavior explicitly: escaped MarkdownV2/HTML or plain text with
  code-aware splitting. Never pass raw model output as Telegram markup.
- Add cancellation and per-chat request serialization so rapid messages do not race
  history or interleave streamed edits.

Exit criterion: long Unicode/code responses arrive in valid ordered chunks, and a
second message cannot corrupt the active turn.

## Phase 2 — errors, resilience, and observability

- Classify backend timeouts, rate limits, invalid model IDs, context overflow, NIM
  unavailability, Telegram errors, and internal failures into safe user messages.
- Keep detailed exceptions in logs; stop returning raw backend exceptions to users.
- Add bounded retries with jitter only for transient/idempotent failures and expose a
  `/cancel` command for long generations.
- Emit structured logs with request/chat correlation IDs, model, latency, token usage,
  outcome, and retry count; hash user/chat identifiers instead of logging content.
- Add a bot healthcheck and optional Prometheus metrics endpoint on the internal
  network. Track request counts, failures, time-to-first-token, completion latency,
  input/output tokens, active generations, and tool latency.
- Add SQLite schema versioning, retention controls, and a backup/restore procedure.

Exit criterion: operators can distinguish user/config/backend failures without
reading message content, and transient outages recover cleanly.

## Phase 3 — per-chat controls

- Replace `/think`'s boolean with a per-model reasoning policy (`off`, `low`,
  `medium`, `high`) translated by adapters: Nemotron chat-template arguments,
  GPT-OSS `reasoning_effort`, Qwen thinking controls, or unsupported.
- Add `/model`, `/settings`, `/temperature`, `/system`, `/memory`, and `/status`, with
  allowlisted values and admin-only global changes.
- Store settings with an explicit schema and reset semantics. Report unsupported
  controls rather than silently treating them as no-ops.
- Add token-budgeted history truncation and optional rolling summaries instead of
  limiting history by message count alone.

Exit criterion: every visible setting accurately maps to the selected model and
survives restarts.

## Phase 4 — attachments and multimodal input

- Download Telegram photos and documents with configurable size/MIME allowlists,
  timeouts, temporary-file cleanup, and protection against archive/decompression
  bombs.
- For vision-capable NIMs, encode supported images into the OpenAI-compatible message
  content format. For text/PDF files, extract bounded text with page/source metadata.
- Add optional ASR NIM integration for voice notes; keep transcription as a separate
  service/capability from the chat model.
- Store attachment metadata and derived text, not binary payloads, unless retention is
  explicitly enabled. Provide `/forget_files`.
- Reject unsupported media clearly based on the selected model capability preset.

Exit criterion: supported attachments are bounded, attributable, and never silently
discarded or sent to an incompatible model.

## Phase 5 — native tools and search

- Implement a server-side tool registry with typed JSON schemas, per-tool timeouts,
  output-size limits, audit logging, and an allowlist per chat/user.
- Start with read-only web search through SearXNG. The bot executes tool calls,
  appends tool results, and continues completions until a bounded iteration limit.
- Normalize model-specific tool-call formats behind adapters and test malformed,
  repeated, parallel, and hallucinated calls.
- Add SSRF defenses: fixed SearXNG endpoint, URL/domain policy, private-address
  blocking for any fetch tool, content-type validation, and prompt-injection labels
  around untrusted results.
- Require explicit confirmation before any future tool that mutates external state.
- Return source links and expose `/tools` plus a per-chat tools on/off control.

Exit criterion: search works in Telegram with citations, bounded loops, and no generic
network fetch or state-changing capability enabled by default.

## Suggested delivery slices

1. Refactor/tests/config validation.
2. Safe splitter plus streaming/cancellation.
3. Error taxonomy, structured logs, health and metrics.
4. Per-model capability adapters and per-chat settings.
5. Text/image/PDF attachments, then voice through ASR.
6. Read-only SearXNG tool loop, followed by separately reviewed tools.
