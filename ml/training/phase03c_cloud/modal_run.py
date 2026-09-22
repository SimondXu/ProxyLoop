#!/usr/bin/env python
"""Phase 03C Stage 2 + Stage 3 on Modal, in one GPU container.

Same three commands as ``run.sh`` -- ``train.py --merge``, ``eval_heldout.py``
and ``eval_heldout.py --dev`` -- wrapped in one Modal Function.  The local
entrypoint uploads ``data/experiments/phase-03c/cloud-bundle/`` to a Volume
once and downloads ``phase03c-upload.tar.gz`` back into
``data/experiments/phase-03c/training/<run>/``.

    pip install modal && modal setup                      # once, browser auth
    modal run ml/training/phase03c_cloud/modal_run.py --smoke
    modal run --detach ml/training/phase03c_cloud/modal_run.py
    modal run ml/training/phase03c_cloud/modal_run.py --download-only

Training writes to the container's local disk, so the 16 GB merged weights
and the intermediate checkpoints never reach a Volume.  The adapter, the
manifests, the reports and the logs are mirrored to the output Volume twice:
right after training (so an eval failure cannot lose the expensive part) and
again after the arms finish.  The Hugging Face cache is a Volume, so the base
model is downloaded once across the smoke and the real run.
"""

import shlex
import shutil
import subprocess
import time
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
LOCAL_BUNDLE = REPO_ROOT / "data/experiments/phase-03c/cloud-bundle"
LOCAL_TRAINING = REPO_ROOT / "data/experiments/phase-03c/training"

APP_NAME = "phase03c-stage2"
DEFAULT_RUN = "cloud-run-01"
UPLOAD_TARBALL = "phase03c-upload.tar.gz"
HOURS = 60 * 60

# Remote paths: three Volumes plus the container's own disk for the heavy parts.
BUNDLE_DIR = "/bundle"
OUT_DIR = "/out"
HF_CACHE_DIR = "/hf"
PACKAGE_DIR = "/root/phase03c_cloud"
SCRATCH_DIR = "/scratch"

# 80 GB holds the contract's effective batch (4 x 4 at max_length 2304) without
# the 40 GB fallback flags; H100 is the fallback when A100s are unavailable.
GPU = ["A100-80GB", "H100"]

BUNDLE_VOLUME = modal.Volume.from_name("phase03c-bundle", create_if_missing=True)
OUT_VOLUME = modal.Volume.from_name("phase03c-out", create_if_missing=True)
HF_VOLUME = modal.Volume.from_name("phase03c-hf-cache", create_if_missing=True)

IMAGE = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements(str(HERE / "requirements.txt"))
    .env(
        {
            "HF_HOME": HF_CACHE_DIR,
            "PYTHONUNBUFFERED": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    .add_local_dir(str(HERE), PACKAGE_DIR, ignore=["**/__pycache__", "**/*.pyc"])
)

app = modal.App(APP_NAME)

VERSION_PROBE = (
    "import torch, vllm, trl, peft, transformers, datasets;"
    " print('vllm', vllm.__version__, 'trl', trl.__version__,"
    " 'peft', peft.__version__, 'transformers', transformers.__version__,"
    " 'datasets', datasets.__version__)"
)


def log(message: str) -> None:
    print(f"[modal] {time.strftime('%H:%M:%S')} {message}", flush=True)


def run_logged(command: list[str], log_path: Path) -> None:
    """Run a command from the package dir, teeing its output like ``run.sh``."""
    joined = " ".join(shlex.quote(part) for part in command)
    log(f"$ {joined}")
    subprocess.run(
        [
            "bash",
            "-o",
            "pipefail",
            "-c",
            f"{joined} 2>&1 | tee -a {shlex.quote(str(log_path))}",
        ],
        check=True,
        cwd=PACKAGE_DIR,
    )


def mirror(source: Path, target: Path) -> None:
    if not source.exists():
        log(f"skip mirror, missing {source}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)
    else:
        shutil.copy2(source, target)
    log(f"mirrored {source} -> {target}")


@app.function(
    image=IMAGE,
    gpu=GPU,
    timeout=12 * HOURS,
    volumes={
        BUNDLE_DIR: BUNDLE_VOLUME,
        OUT_DIR: OUT_VOLUME,
        HF_CACHE_DIR: HF_VOLUME,
    },
)
def run_stage2(
    run: str = DEFAULT_RUN,
    train_flags: str = "",
    eval_limit: int = 0,
    skip_dev_eval: bool = False,
) -> dict:
    """Train, evaluate the arms, and leave the upload set on the out Volume."""
    import torch

    started = time.time()
    gpu_name = torch.cuda.get_device_name(0)
    log(f"gpu {gpu_name} torch {torch.__version__} cuda {torch.version.cuda}")
    run_logged(["python", "-c", VERSION_PROBE], Path("/dev/null"))

    bundle = Path(BUNDLE_DIR)
    if not (bundle / "bundle-manifest.json").is_file():
        raise SystemExit(f"missing {bundle}/bundle-manifest.json -- upload the bundle")

    work = Path(SCRATCH_DIR) / run
    train_dir = work / "train"
    eval_dir = work / "eval"
    out_run = Path(OUT_DIR) / run
    work.mkdir(parents=True, exist_ok=True)
    out_run.mkdir(parents=True, exist_ok=True)

    train_log = work / "train.log"
    run_logged(
        [
            "python",
            "train.py",
            "--bundle-dir",
            str(bundle),
            "--out-dir",
            str(train_dir),
            "--merge",
            *shlex.split(train_flags),
        ],
        train_log,
    )
    trained = time.time()
    log(f"training finished in {trained - started:.0f}s")

    # Checkpoint the expensive half before the vLLM arms can fail.
    for name in ("run-manifest.json", "dev-evals.jsonl", "adapter"):
        mirror(train_dir / name, out_run / "train" / name)
    mirror(train_log, out_run / "train.log")
    OUT_VOLUME.commit()

    limit_flags = ["--limit", str(eval_limit)] if eval_limit > 0 else []
    heldout_log = work / "eval-heldout.log"
    run_logged(
        [
            "python",
            "eval_heldout.py",
            "--bundle-dir",
            str(bundle),
            "--run-dir",
            str(train_dir),
            "--out-dir",
            str(eval_dir),
            *limit_flags,
        ],
        heldout_log,
    )

    dev_log = work / "eval-dev.log"
    if not skip_dev_eval:
        run_logged(
            [
                "python",
                "eval_heldout.py",
                "--bundle-dir",
                str(bundle),
                "--run-dir",
                str(train_dir),
                "--out-dir",
                str(eval_dir),
                "--dev",
                "--latency-rows",
                "0",
                *limit_flags,
            ],
            dev_log,
        )

    members = [
        "train/run-manifest.json",
        "train/dev-evals.jsonl",
        "train/adapter",
        "eval/heldout-report.json",
        "eval/dev-report.json",
        "train.log",
        "eval-heldout.log",
        "eval-dev.log",
    ]
    present = [name for name in members if (work / name).exists()]
    tarball = work / UPLOAD_TARBALL
    subprocess.run(
        ["tar", "-czf", str(tarball), "-C", str(work), *present],
        check=True,
    )
    mirror(tarball, out_run / UPLOAD_TARBALL)
    mirror(eval_dir, out_run / "eval")
    for name in ("eval-heldout.log", "eval-dev.log"):
        mirror(work / name, out_run / name)
    OUT_VOLUME.commit()

    result = {
        "run": run,
        "gpu": gpu_name,
        "train_seconds": round(trained - started),
        "total_seconds": round(time.time() - started),
        "tarball_bytes": tarball.stat().st_size,
        "tarball_members": present,
    }
    log(f"done {result}")
    return result


@app.local_entrypoint()
def main(
    run: str = DEFAULT_RUN,
    smoke: bool = False,
    train_flags: str = "",
    skip_upload: bool = False,
    skip_download: bool = False,
    download_only: bool = False,
    bundle_dir: str = "",
    download_dir: str = "",
) -> None:
    """Upload the bundle, run Stage 2 + 3 on one GPU, download the upload set."""
    if smoke and run == DEFAULT_RUN:
        run = "smoke-01"
    target = Path(download_dir) if download_dir else LOCAL_TRAINING / run

    if not download_only:
        if not skip_upload:
            local_bundle = Path(bundle_dir) if bundle_dir else LOCAL_BUNDLE
            manifest = local_bundle / "bundle-manifest.json"
            if not manifest.is_file():
                raise SystemExit(
                    f"missing {manifest} -- run `make phase03c-cloud-bundle` first"
                )
            print(f"uploading {local_bundle} -> volume phase03c-bundle")
            with BUNDLE_VOLUME.batch_upload(force=True) as batch:
                batch.put_directory(str(local_bundle), "/")

        flags = " ".join(
            part for part in ("--smoke" if smoke else "", train_flags) if part
        )
        result = run_stage2.remote(
            run=run,
            train_flags=flags,
            eval_limit=8 if smoke else 0,
            skip_dev_eval=smoke,
        )
        print(result)

    if skip_download:
        print(f"left {run}/{UPLOAD_TARBALL} on volume phase03c-out")
        return

    target.mkdir(parents=True, exist_ok=True)
    tarball = target / UPLOAD_TARBALL
    print(f"downloading {run}/{UPLOAD_TARBALL} -> {tarball}")
    with tarball.open("wb") as handle:
        for chunk in OUT_VOLUME.read_file(f"{run}/{UPLOAD_TARBALL}"):
            handle.write(chunk)
    print(f"wrote {tarball} ({tarball.stat().st_size} bytes)")
    print(f"next: tar -xzf {tarball} -C {target}")
