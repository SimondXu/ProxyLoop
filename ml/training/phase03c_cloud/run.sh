#!/usr/bin/env bash
# Phase 03C Stage 2 + Stage 3 on one CUDA box, end to end.
#
#   bash run.sh <bundle-dir> <out-dir> [extra train.py flags]
#
# Env: PHASE03C_SKIP_INSTALL=1 skips pip; HF_HOME redirects the model cache;
# PHASE03C_TRAIN_FLAGS adds flags to train.py (e.g. "--smoke" or
# "--per-device-train-batch-size 2 --gradient-accumulation-steps 8" on 40 GB).
set -euo pipefail

BUNDLE=${1:?usage: run.sh <bundle-dir> <out-dir>}
OUT=${2:?usage: run.sh <bundle-dir> <out-dir>}
shift 2
cd "$(dirname "$0")"

if [[ "${PHASE03C_SKIP_INSTALL:-0}" != "1" ]]; then
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
fi
python - <<'PY'
import torch, vllm, trl, peft, transformers
print("torch", torch.__version__, "cuda", torch.version.cuda, "gpu", torch.cuda.get_device_name(0))
print("vllm", vllm.__version__, "trl", trl.__version__, "peft", peft.__version__, "transformers", transformers.__version__)
PY

test -f "$BUNDLE/bundle-manifest.json" || { echo "missing $BUNDLE/bundle-manifest.json" >&2; exit 1; }
mkdir -p "$OUT"

# Stage 2: LoRA SFT, dev evals every 100 steps, adapter + merged bf16 export.
python train.py --bundle-dir "$BUNDLE" --out-dir "$OUT/train" --merge \
  ${PHASE03C_TRAIN_FLAGS:-} "$@" 2>&1 | tee "$OUT/train.log"

# Stage 3: A1-A4 over heldout.jsonl (~240 rows), then A1-A4 over dev-eval.jsonl.
python eval_heldout.py --bundle-dir "$BUNDLE" --run-dir "$OUT/train" \
  --out-dir "$OUT/eval" 2>&1 | tee "$OUT/eval-heldout.log"
python eval_heldout.py --bundle-dir "$BUNDLE" --run-dir "$OUT/train" \
  --out-dir "$OUT/eval" --dev --latency-rows 0 2>&1 | tee "$OUT/eval-dev.log"

# Upload set: manifests, dev evals, reports, logs, the selected adapter.
# Merged weights (~16 GB) stay on the box; the adapter reproduces them.
tar -czf "$OUT/phase03c-upload.tar.gz" -C "$OUT" \
  train/run-manifest.json train/dev-evals.jsonl train/adapter \
  eval/heldout-report.json eval/dev-report.json \
  train.log eval-heldout.log eval-dev.log
echo "upload $OUT/phase03c-upload.tar.gz"
