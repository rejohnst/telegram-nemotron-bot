# NVIDIA's minimum vLLM revision for Bolt, with an ARM64/AMD64 manifest pin.
FROM vllm/vllm-openai:nightly-77154ca6116ae34cbfe314beef1016bde9b63989@sha256:a7deff2c216def98c193352aca50fb03a2ee29231355b3033dc3789009f6d23e

ARG MODEL_REVISION
RUN python3 -m pip install --no-cache-dir b12x==1.5.1

# Pin executable parser code to the same revision as model/configuration code.
ADD --chmod=644 https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB/resolve/${MODEL_REVISION}/ultra_v3_reasoning_parser.py /opt/bolt/ultra_v3_reasoning_parser.py

COPY start.sh /opt/bolt/start.sh
ENTRYPOINT ["bash", "/opt/bolt/start.sh"]
