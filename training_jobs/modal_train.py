"""Modal app: the S0 SFT smoke (ADR-0003), make -f mk/mod.mk train-smoke (root, G)."""

# pyright: basic

import json
import subprocess
import time
from pathlib import Path

import modal

from serving import config, modal_vllm
from training_jobs import sft

REPO = Path(__file__).resolve().parents[1]
GIT_SHA = ["git", "describe", "--always", "--dirty", "--abbrev=40", "--exclude=*"]
app = modal.App("proxyloop-train")
image = (
    modal.Image.from_registry(sft.BASE_IMAGE, add_python="3.12")
    .uv_pip_install(sft.TORCH, index_url=sft.TORCH_INDEX)
    .uv_pip_install(*sft.REST)
    .env({"CC": "gcc", "CXX": "g++", "CAUSAL_CONV1D_FORCE_BUILD": "TRUE"})  # ADR-0003
    .env({"TORCH_CUDA_ARCH_LIST": "9.0", "HF_HOME": modal_vllm.HF_DIR})
    .uv_pip_install(sft.CONV1D, extra_options="--no-build-isolation")
    .add_local_dir(REPO / "src/proxyloop", "/root/proxyloop", ignore=["**/*.pyc"])
    .add_local_python_source("serving")
)


@app.function(image=image, gpu=config.GPU, volumes=modal_vllm.VOLUMES, timeout=7200)
def train_smoke(run_id: str, views: list[tuple[str, str]], git_sha: str) -> dict:
    run_dir = Path(modal_vllm.ADAPTER_DIR) / "train" / run_id
    commit = modal_vllm.adapter_volume.commit
    return sft.train(modal_vllm.download_model, run_dir, views, git_sha, commit)


@app.local_entrypoint()
def main(out: str = "docs/decisions/data/peft-train-smoke.json", run_id: str = ""):
    golden = sorted((REPO / "tests/golden/views").glob("*.json"))
    docs = [json.loads(p.read_text("utf-8")) for p in golden]
    run_id = run_id or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    print(json.dumps({"run_id": run_id}), flush=True)
    views = [(d["profile"], json.dumps(d["view"])) for d in docs]
    sha = subprocess.check_output(GIT_SHA, text=True).strip()  # "-dirty" if uncommitted
    sft.write_json(Path(out), train_smoke.remote(run_id, views, sha))
