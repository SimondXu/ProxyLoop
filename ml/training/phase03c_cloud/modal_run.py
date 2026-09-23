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

import os
import shlex
import shutil
import subprocess
import sysconfig
import time
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent
BUNDLE_SUBPATH = "data/experiments/phase-03c/cloud-bundle"
TRAINING_SUBPATH = "data/experiments/phase-03c/training"

APP_NAME = "phase03c-stage2"
DEFAULT_RUN = "cloud-run-01"
UPLOAD_TARBALL = "phase03c-upload.tar.gz"
DEV_ROUND_MEMBERS = ("eval/dev-report.json", "eval-dev.log")
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
            # vLLM's flashinfer sampler JIT-compiles kernels on first use, and
            # the wheels' nvcc (13.4), torch's CUDA (13.0) and flashinfer's own
            # bundled cccl headers do not agree. The arms decode greedily, so
            # the PyTorch-native sampler is the reference path anyway.
            "VLLM_USE_FLASHINFER_SAMPLER": "0",
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


def repo_root() -> Path:
    """Repository root. Only defined locally: remotely this file sits in /root."""
    return HERE.parents[2]


def ensure_cuda_home() -> str | None:
    """Diagnostic: report and export the nvcc the CUDA wheels ship.

    Nothing in this pipeline compiles any more -- flashinfer's JIT sampler,
    the one consumer, is disabled through VLLM_USE_FLASHINFER_SAMPLER because
    its bundled cccl headers reject the wheels' nvcc. This stays so the log
    records which toolkit was present if something starts compiling again.
    """
    if os.environ.get("CUDA_HOME"):
        return os.environ["CUDA_HOME"]
    site_packages = Path(sysconfig.get_paths()["purelib"])
    for nvcc in sorted(site_packages.glob("nvidia/*/bin/nvcc")):
        home = str(nvcc.parent.parent)
        os.environ["CUDA_HOME"] = home
        os.environ["CUDA_PATH"] = home
        return home
    return None


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


def save_training_evidence(train_dir: Path, train_log: Path, out_run: Path) -> None:
    """Mirror everything train.py has written so far, ignoring what is absent."""
    for name in ("run-manifest.json", "dev-evals.jsonl", "adapter"):
        mirror(train_dir / name, out_run / "train" / name)
    mirror(train_log, out_run / "train.log")
    OUT_VOLUME.commit()


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
    log(f"cuda_home {ensure_cuda_home()}")
    # Keep JIT/compile caches on the Volume so a rerun reuses them. Set here
    # and not in the image: pip's own ~/.cache obeys XDG_CACHE_HOME, so an
    # image-level value populates /hf during the build and the Volume then
    # refuses to mount on a non-empty path.
    jit_cache = Path(HF_CACHE_DIR) / "cache"
    jit_cache.mkdir(parents=True, exist_ok=True)
    os.environ["XDG_CACHE_HOME"] = str(jit_cache)

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
    try:
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
    finally:
        # Whatever the run produced before it stopped is the only copy: the
        # work dir is the container's own disk. dev-evals.jsonl is appended
        # per eval step, so a failure at hour 4 still leaves real evidence.
        save_training_evidence(train_dir, train_log, out_run)
    trained = time.time()
    log(f"training finished in {trained - started:.0f}s")

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
    # The held-out report is Stage 3's contracted artifact and it is complete
    # now. The dev round below loads two more engines over 400 rows instead of
    # 240; if it fails, this must already be on the Volume.
    mirror(eval_dir, out_run / "eval")
    mirror(heldout_log, out_run / "eval-heldout.log")
    OUT_VOLUME.commit()

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
    if skip_dev_eval:
        # Only the dev ROUND's own outputs. train/dev-evals.jsonl is the
        # per-step record including the untuned step 0 and is always required.
        members = [name for name in members if name not in DEV_ROUND_MEMBERS]
    missing = [name for name in members if not (work / name).exists()]
    if missing:
        raise SystemExit(f"upload set incomplete, missing: {missing}")
    present = members
    tarball = work / UPLOAD_TARBALL
    subprocess.run(
        ["tar", "-czf", str(tarball), "-C", str(work), *present],
        check=True,
    )
    HF_VOLUME.commit()
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
    if smoke and not run.startswith("smoke"):
        # Otherwise a smoke writes 32-row artifacts over the real run's
        # directory and its tarball on the out Volume.
        raise SystemExit(f"--smoke needs a run name starting with 'smoke', got {run!r}")
    if download_only and skip_download:
        raise SystemExit("--download-only with --skip-download does nothing")
    target = (
        Path(download_dir) if download_dir else repo_root() / TRAINING_SUBPATH / run
    )

    if not download_only:
        if not skip_upload:
            local_bundle = (
                Path(bundle_dir) if bundle_dir else repo_root() / BUNDLE_SUBPATH
            )
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
