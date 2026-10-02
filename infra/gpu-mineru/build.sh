#!/usr/bin/env bash
# MinerU 4 이미지 빌드 (처음 한 번, 20~40분: vLLM 베이스 이미지 + 모델 내려받기)
# CUDA 12.9 드라이버면 CUDA=cu129 bash build.sh
set -euo pipefail
cd "$(dirname "$0")"
[ -d mineru-src ] || git clone --depth 1 https://github.com/opendatalab/MinerU mineru-src
cd mineru-src && git pull -q --ff-only || true
if [ "${CUDA:-}" = "cu129" ]; then
  sed -i 's|^FROM vllm/vllm-openai:v0.21.0$|# &|; s|^# FROM vllm/vllm-openai:v0.21.0-cu129|FROM vllm/vllm-openai:v0.21.0-cu129|' docker/global/Dockerfile
fi
docker build -t mineru:4 -f docker/global/Dockerfile .
docker run --rm --entrypoint python3 mineru:4 -c 'from mineru.version import __version__; print("MinerU", __version__)'
