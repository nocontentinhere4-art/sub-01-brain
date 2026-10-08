#!/bin/bash
# ARDY (NVIDIA, Apache-2.0 code; checkpoints under the NVIDIA Open Model License) on one RunPod pod, run by
# analysis/runpod_job.py: uploads are in /in (gen.py, specs.json), results go to /out (fetched, then the pod is deleted).
#
# Text encoder without the gated Meta repo: ARDY's LLM2Vec encoder is the public McGill-NLP LoRA adapters (MIT) on top of
# Meta-Llama-3-8B-Instruct. NousResearch/Meta-Llama-3-8B-Instruct is a public re-upload of the same weights under the same
# Llama 3 Community License: its four safetensors shards have the same SHA-256 as meta-llama's (checked below, recorded in
# /out/llama_shards.txt). The adapter's base_model_name_or_path is pointed at that local copy. No token is used anywhere.
set -uxo pipefail
cd /work
nvidia-smi --query-gpu=name,memory.total --format=csv
python3 -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"

git clone --depth 1 https://github.com/nv-tlabs/ardy /work/ardy
cd /work/ardy && git rev-parse HEAD | tee /out/ardy_commit.txt
# deps first (so a failed C++ build of the motion-correction extension cannot take the whole install down)
pip install -q cmake ninja "numpy<2" scipy hydra-core omegaconf pydantic "transformers==5.8.1" "peft>=0.19" einops \
    "vector-quantize-pytorch>=1.25,<1.26" "huggingface_hub>=1.0" safetensors gradio_client tqdm packaging 2>&1 | tail -3
pip install -q -e . 2>&1 | tail -5 || echo "ARDY editable install failed; using PYTHONPATH (no foot-skate post-process)"
export PYTHONPATH=/work/ardy:${PYTHONPATH:-}
python3 -c "import ardy; print('ardy import ok')"

TE=/work/te
mkdir -p $TE/McGill-NLP $TE/NousResearch
hf download McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp --local-dir $TE/McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp
hf download McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised --local-dir $TE/McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised
hf download NousResearch/Meta-Llama-3-8B-Instruct --local-dir $TE/NousResearch/Meta-Llama-3-8B-Instruct --exclude "original/*"
# the shards' SHA-256 vs meta-llama/Meta-Llama-3-8B-Instruct (from the Hub's own file metadata, 2026-10-02)
cat > /out/llama_shards_expected.txt <<'EOF'
d8cf9c4d0dd972e1a2131bfe656235ee98221679711a3beef6d46dadf0f20b5c  model-00001-of-00004.safetensors
8d4782b4a69ef03845159ce1a15e272aadaaf134dc138d68f616098e8531729c  model-00002-of-00004.safetensors
3acdd690e65c24f42a24581b8467af98bd3ca357444580f8012aacd2bd607921  model-00003-of-00004.safetensors
67e9ad31c8c32abf3a55ee7fc7217b3ecb35fd3c74d98a5bd233e0e4d6964f46  model-00004-of-00004.safetensors
EOF
(cd $TE/NousResearch/Meta-Llama-3-8B-Instruct && sha256sum model-0000*.safetensors | tee /out/llama_shards.txt && sha256sum -c /out/llama_shards_expected.txt | tee /out/llama_shards_check.txt)
# transformers 5.8 loads a LOCAL adapter directory that has its own config.json from that directory (it follows the
# adapter's base_model_name_or_path only for Hub ids), so the base weights go into the adapter's directory: hard links
# to the verified shards. from_pretrained then loads Llama and, finding adapter_config.json beside it, the MNTP LoRA.
MNTP=$TE/McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp
for f in $TE/NousResearch/Meta-Llama-3-8B-Instruct/model-0000*.safetensors $TE/NousResearch/Meta-Llama-3-8B-Instruct/model.safetensors.index.json; do ln -f "$f" "$MNTP/$(basename $f)" || cp "$f" "$MNTP/"; done
ls -la $MNTP
export TEXT_ENCODERS_DIR=$TE
export HF_HUB_DISABLE_TELEMETRY=1
mkdir -p /out/ardy
python3 /in/gen.py /in/specs.json /out/ardy 2>&1 | tee /out/gen.log
cd /out && tar czf ardy_out.tar.gz ardy && ls -la /out
