"""Modal app: the pinned vLLM server for Qwen3.5-9B and the LoRA-ladder job (ADR-0002). Root-run.

    modal run -m serving.modal_vllm --out docs/decisions/data/vllm-lora-ladder.json  # ladder first
    make -f mk/mod.mk serve-probe                                                      # then serve
PL_SERVE_VARIANT (pinned | prefix-align) and PL_ZERO_LORA (the ladder rung directory served as
the zero-LoRA slot) are read at deploy time and baked into the image env, so the container runs
exactly the deployed configuration.
"""

import json
import os
import subprocess
import time
from importlib import metadata
from pathlib import Path

import modal

from serving import config

VARIANT = os.environ.get("PL_SERVE_VARIANT", "pinned")
ZERO_LORA = os.environ.get("PL_ZERO_LORA", "zero-all")
if ZERO_LORA not in config.RUNGS:
    raise ValueError(f"PL_ZERO_LORA must be one of {sorted(config.RUNGS)}")
HF_DIR, ADAPTER_DIR, ATTEST_FILE = "/hf", "/adapters", "/tmp/pl-attest.json"
hf_volume = modal.Volume.from_name("proxyloop-hf-cache", create_if_missing=True)
adapter_volume = modal.Volume.from_name("proxyloop-adapters", create_if_missing=True)
VOLUMES = {HF_DIR: hf_volume, ADAPTER_DIR: adapter_volume}

base_image = modal.Image.from_registry(
    config.VLLM_IMAGE,  # ships python3 only, with ENTRYPOINT ["vllm", "serve"]
    setup_dockerfile_commands=["RUN ln -s /usr/bin/python3 /usr/local/bin/python", "ENTRYPOINT []"],
).env({"HF_HOME": HF_DIR, "PL_SERVE_VARIANT": VARIANT, "PL_ZERO_LORA": ZERO_LORA})
image = base_image.add_local_python_source("serving")
ladder_image = base_image.uv_pip_install(
    f"peft=={config.PEFT_VERSION}", f"accelerate=={config.ACCELERATE_VERSION}"
).add_local_python_source("serving")
app = modal.App(config.app_name(VARIANT))


def download_model() -> Path:
    from huggingface_hub import snapshot_download

    path = Path(snapshot_download(config.MODEL_ID, revision=config.MODEL_REVISION))
    hf_volume.commit()
    return path


def runtime() -> dict:
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                         capture_output=True, text=True, check=True).stdout.strip()
    return {"vllm_version": metadata.version("vllm"), "gpu_name": gpu}


@app.function(image=image, gpu=config.GPU, volumes=VOLUMES, timeout=60 * 60,
              secrets=[modal.Secret.from_name(config.SECRET_NAME)],
              scaledown_window=5 * 60, max_containers=1)
@modal.concurrent(max_inputs=64)
@modal.web_server(port=config.PORT, startup_timeout=30 * 60)
def serve() -> None:
    started_at = time.time()
    if not os.environ.get("VLLM_API_KEY"):
        raise RuntimeError("VLLM_API_KEY missing: the Modal secret proxyloop-vllm must provide it")
    from serving.attest import attest_files

    model_dir, zero_dir = download_model(), Path(ADAPTER_DIR) / ZERO_LORA
    doc = attest_files(model_dir, {config.ZERO_LORA_NAME: zero_dir}, Path(HF_DIR) / "pl-attest-cache.json")
    hf_volume.commit()
    args = config.serve_args(str(model_dir), VARIANT, str(zero_dir))
    doc["runtime"] = {**runtime(), "variant": VARIANT, "zero_lora_rung": ZERO_LORA,
                      "serve_args": args, "container_started_at": started_at}
    Path(ATTEST_FILE).write_text(json.dumps(doc))
    env = {**os.environ, "PL_ATTEST_FILE": ATTEST_FILE, "HF_HUB_OFFLINE": "1", "PYTHONPATH": "/root"}
    subprocess.Popen(args, env=env, cwd="/root")


@app.function(image=ladder_image, gpu=config.GPU, volumes=VOLUMES, timeout=60 * 60)
def lora_ladder() -> dict:
    from serving import zero_lora

    result = zero_lora.run(download_model(), Path(ADAPTER_DIR))
    adapter_volume.commit()
    return {**result, "runtime": {**runtime(), "peft_version": metadata.version("peft")}}


@app.local_entrypoint()
def main(out: str = "docs/decisions/data/vllm-lora-ladder.json") -> None:
    result = lora_ladder.remote()
    Path(out).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summary"], indent=2))
