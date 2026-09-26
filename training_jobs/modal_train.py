"""Modal app: the S0 SFT smoke on one H100 (ADR-0003). Root-run: make train-smoke.
Artefacts go to the adapters volume, train/<run_id>/. A preempted input restarts with
the same run_id and resumes from its latest complete checkpoint (after a local
disconnect, rerun with --run-id <id>). Metrics stream as JSON lines.
"""

# pyright: basic

import json
import time
from pathlib import Path

import modal

from serving import config, modal_vllm
from training_jobs import sft

REPO = Path(__file__).resolve().parents[1]
app = modal.App("proxyloop-train")
image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(*sft.PINS)
    .env({"HF_HOME": modal_vllm.HF_DIR})
    .add_local_dir(REPO / "src/proxyloop", "/root/proxyloop", ignore=["**/*.pyc"])
    .add_local_python_source("serving")
)


@app.function(image=image, gpu=config.GPU, volumes=modal_vllm.VOLUMES, timeout=7200)
def train_smoke(run_id: str, views: list[tuple[str, str]]) -> dict:
    run_dir = Path(modal_vllm.ADAPTER_DIR) / "train" / run_id
    commit = modal_vllm.adapter_volume.commit
    return sft.train(modal_vllm.download_model(), run_dir, views, commit)


@app.local_entrypoint()
def main(out: str = "docs/decisions/data/peft-train-smoke.json", run_id: str = ""):
    golden = sorted((REPO / "tests/golden/views").glob("*.json"))
    docs = [json.loads(p.read_text("utf-8")) for p in golden]
    run_id = run_id or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    print(json.dumps({"run_id": run_id}), flush=True)
    views = [(d["profile"], json.dumps(d["view"])) for d in docs]
    sft.write_json(Path(out), train_smoke.remote(run_id, views))
