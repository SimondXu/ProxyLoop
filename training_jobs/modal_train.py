"""Modal app: SFT runs (ADR-0003), root-run (G): the S0 smoke is ``::main`` (make
train-smoke), pull-through training ``::pull_through`` (make pull-through)."""

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


def _train(run_id: str, rows: list, sha: str, recipe: dict, lora: dict, card: dict):
    run_dir = Path(modal_vllm.ADAPTER_DIR) / "train" / run_id
    commit, download = modal_vllm.adapter_volume.commit, modal_vllm.download_model
    return sft.train(download, run_dir, rows, sha, commit, recipe, lora, card)


@app.function(image=image, gpu=config.GPU, volumes=modal_vllm.VOLUMES, timeout=7200)
def train_smoke(run_id: str, views: list[tuple[str, str]], git_sha: str) -> dict:
    card = {"rows": "synthetic-smoke"}
    return _train(run_id, sft.smoke_rows(views), git_sha, sft.SMOKE, sft.LORA, card)


@app.function(image=image, gpu=config.GPU, volumes=modal_vllm.VOLUMES, timeout=7200)
def train_rows(run_id: str, rows: list, git_sha: str, card: dict) -> dict:
    """Pull-through (TRAINING §9 step 3) on the rows pull_through.py selected."""
    recipe = sft.pull_through_recipe(len(rows))
    card = card | {"batch_note": sft.PT_BATCH_NOTE}
    return _train(run_id, rows, git_sha, recipe, sft.LORA_PT, card)


@app.local_entrypoint()
def main(out: str = "docs/decisions/data/peft-train-smoke.json", run_id: str = ""):
    golden = sorted((REPO / "tests/golden/views").glob("*.json"))
    docs = [json.loads(p.read_text("utf-8")) for p in golden]
    run_id = run_id or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    print(json.dumps({"run_id": run_id}), flush=True)
    views = [(d["profile"], json.dumps(d["view"])) for d in docs]
    sha = subprocess.check_output(GIT_SHA, text=True).strip()  # "-dirty" if uncommitted
    sft.write_json(Path(out), train_smoke.remote(run_id, views, sha))


@app.local_entrypoint()
def pull_through(rows: str, out: str, run_id: str = ""):
    """``rows``: the JSON written by ``proxyloop.training.pull_through select``."""
    doc = json.loads(Path(rows).read_text("utf-8"))
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    run_id = run_id or f"pt-{doc['fp8']}-{stamp}"
    print(json.dumps({"run_id": run_id}), flush=True)
    card = {
        k: doc[k] for k in ("source", "dataset_hash", "fingerprint", "adapter_name")
    }
    sha = subprocess.check_output(GIT_SHA, text=True).strip()  # "-dirty" if uncommitted
    sft.write_json(Path(out), train_rows.remote(run_id, doc["rows"], sha, card))
