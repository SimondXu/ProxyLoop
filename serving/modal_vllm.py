"""Modal app: the pinned vLLM server for Qwen3.5-9B (ADR-0002).
Root-run: `make -f mk/mod.mk serve-*`.

PL_SERVE_VARIANT (pinned | prefix-align) and PL_LORA_RUNG (all | attn-mlp: the ladder
rung whose zero and live adapters fill the two LoRA slots) are read at deploy time and
baked into the image env, so the container runs exactly the deployed configuration. The
container exits as soon as vLLM exits or anything before it fails, so a dead server
never holds the GPU.
"""

import json
import os
import subprocess
import sys
import threading
import time
import traceback
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any

import modal

from serving import config

VARIANT = os.environ.get("PL_SERVE_VARIANT", "pinned")
RUNG = os.environ.get("PL_LORA_RUNG", "all")
HF_DIR, ADAPTER_DIR, ATTEST_FILE = "/hf", "/adapters", "/tmp/pl-attest.json"
config.lora_slots(RUNG, ADAPTER_DIR)  # validates RUNG at deploy time
hf_volume = modal.Volume.from_name("proxyloop-hf-cache", create_if_missing=True)
adapter_volume = modal.Volume.from_name("proxyloop-adapters", create_if_missing=True)
VOLUMES: dict[str | PurePosixPath, modal.Volume | modal.CloudBucketMount] = {
    HF_DIR: hf_volume,
    ADAPTER_DIR: adapter_volume,
}
# modal leaves **kwargs untyped on from_registry and its decorators.
base_image = modal.Image.from_registry(  # pyright: ignore[reportUnknownMemberType]
    config.VLLM_IMAGE,  # ships python3 only, with ENTRYPOINT ["vllm", "serve"]
    setup_dockerfile_commands=[
        "RUN ln -s /usr/bin/python3 /usr/local/bin/python",
        "ENTRYPOINT []",
    ],
).env({"HF_HOME": HF_DIR, "PL_SERVE_VARIANT": VARIANT, "PL_LORA_RUNG": RUNG})
app = modal.App(config.app_name(VARIANT))


def download_model() -> Path:
    # huggingface_hub leaves user_agent and tqdm_class partially untyped.
    from huggingface_hub import (
        snapshot_download,  # pyright: ignore[reportUnknownVariableType]
    )

    path = Path(snapshot_download(config.MODEL_ID, revision=config.MODEL_REVISION))
    hf_volume.commit()
    return path


def runtime() -> dict[str, Any]:
    gpu = subprocess.run(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return {"vllm_version": metadata.version("vllm"), "gpu_name": gpu}


def _exit_with(proc: "subprocess.Popen[bytes]") -> None:
    code = proc.wait()
    print(f"[pl] vLLM exited with {code}; stopping the container", flush=True)
    os._exit(1)


def _start_vllm(started_at: float) -> "subprocess.Popen[bytes]":
    if not os.environ.get("VLLM_API_KEY"):
        raise RuntimeError(
            "VLLM_API_KEY missing: the Modal secret proxyloop-vllm must provide it"
        )
    from serving.attest import attest_files

    model_dir, slots = download_model(), config.lora_slots(RUNG, ADAPTER_DIR)
    doc = attest_files(
        model_dir,
        {n: Path(p) for n, p in slots.items()},
        Path(HF_DIR) / "pl-attest-cache.json",
    )
    hf_volume.commit()
    args = config.serve_args(str(model_dir), VARIANT, slots)
    doc["runtime"] = {
        **runtime(),
        "variant": VARIANT,
        "lora_rung": RUNG,
        "serve_args": args,
        "container_started_at": started_at,
    }
    Path(ATTEST_FILE).write_text(json.dumps(doc))
    env = {
        **os.environ,
        "PL_ATTEST_FILE": ATTEST_FILE,
        "HF_HUB_OFFLINE": "1",
        "PYTHONPATH": "/root",
    }
    return subprocess.Popen(args, env=env, cwd="/root")


def _serve() -> None:
    """Start vLLM and tie the container's life to it; any failure exits non-zero at
    once."""
    try:
        proc = _start_vllm(time.time())
    except BaseException:  # not swallowed: logged, then the container exits
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(1)
    threading.Thread(target=_exit_with, args=(proc,), daemon=True).start()


@app.function(  # pyright: ignore[reportUnknownMemberType]
    image=base_image.add_local_python_source("serving"),
    gpu=config.GPU,
    volumes=VOLUMES,
    secrets=[modal.Secret.from_name(config.SECRET_NAME)],
    timeout=60 * 60,
    scaledown_window=5 * 60,
    max_containers=1,
)
@modal.concurrent(max_inputs=64)  # pyright: ignore[reportUnknownMemberType]
@modal.web_server(port=config.PORT, startup_timeout=30 * 60)  # pyright: ignore[reportUnknownMemberType]
def serve() -> None:
    _serve()
