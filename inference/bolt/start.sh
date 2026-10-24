#!/usr/bin/env bash
set -euo pipefail

# Match NVIDIA's setup sequence; run kernel preparation on the target GPU host.
vllm download-kernels
exec vllm serve "$@"
