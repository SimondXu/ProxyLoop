"""PEFT -> MLX LoRA conversion on a synthetic adapter (G2) and the committed
attestation (no weights are needed; CI has no MLX and no adapter file)."""

from __future__ import annotations

import json
import struct
import subprocess
from array import array
from pathlib import Path

import pytest
from proxyloop_evaluation.local_fast.mlx_adapter_conversion import (
    ConversionAttestation,
    convert_peft_lora_to_mlx,
    file_sha256,
    load_attestation,
    read_safetensors_header,
    tensor_content_fingerprint,
    verify_mlx_adapter,
)

ROOT = Path(__file__).resolve().parents[2]
ATTESTATION = ROOT / "ml/serving/phase-03c-cloud-run-01-mlx-attestation.json"
RUN_MANIFEST = (
    ROOT / "data/experiments/phase-03c/training/cloud-run-01/train/run-manifest.json"
)
DEFAULT_MLX_ADAPTER = (
    "data/experiments/phase-03c/training/cloud-run-01/train/mlx/adapters"
)
RANK, ALPHA, HIDDEN, KV, FFN = 2, 4, 3, 2, 5
# module -> (group, in, out) for a tiny Qwen3-shaped block.
MODULES = {
    "q_proj": ("self_attn", HIDDEN, HIDDEN),
    "k_proj": ("self_attn", HIDDEN, KV),
    "v_proj": ("self_attn", HIDDEN, KV),
    "o_proj": ("self_attn", HIDDEN, HIDDEN),
    "gate_proj": ("mlp", HIDDEN, FFN),
    "up_proj": ("mlp", HIDDEN, FFN),
    "down_proj": ("mlp", FFN, HIDDEN),
}


def _write(path: Path, tensors: dict[str, tuple[tuple[int, ...], list[float]]]) -> None:
    header: dict[str, object] = {"__metadata__": {"format": "pt"}}
    blobs: list[bytes] = []
    offset = 0
    for key, (shape, values) in tensors.items():  # insertion order = container order
        data = array("f", values).tobytes()
        header[key] = {
            "dtype": "F32",
            "shape": list(shape),
            "data_offsets": [offset, offset + len(data)],
        }
        blobs.append(data)
        offset += len(data)
    encoded = json.dumps(header).encode()
    path.write_bytes(struct.pack("<Q", len(encoded)) + encoded + b"".join(blobs))


def _peft_tensors(layers: int = 2) -> dict[str, tuple[tuple[int, ...], list[float]]]:
    tensors: dict[str, tuple[tuple[int, ...], list[float]]] = {}
    counter = 0.0
    for layer in range(layers):
        for module, (group, fan_in, fan_out) in MODULES.items():
            prefix = f"base_model.model.model.layers.{layer}.{group}.{module}"
            for side, shape in (("A", (RANK, fan_in)), ("B", (fan_out, RANK))):
                size = shape[0] * shape[1]
                values = [counter + index for index in range(size)]
                counter += size
                tensors[f"{prefix}.lora_{side}.weight"] = (shape, values)
    return tensors


def _peft_dir(
    tmp_path: Path,
    tensors: dict[str, tuple[tuple[int, ...], list[float]]] | None = None,
    **config: object,
) -> tuple[Path, str]:
    source = tmp_path / "peft"
    source.mkdir()
    _write(source / "adapter_model.safetensors", tensors or _peft_tensors())
    base = {
        "peft_type": "LORA",
        "r": RANK,
        "lora_alpha": ALPHA,
        "lora_dropout": 0.05,
        "bias": "none",
        "fan_in_fan_out": False,
        "use_dora": False,
        "use_rslora": False,
        "layers_to_transform": None,
        "modules_to_save": None,
        "rank_pattern": {},
        "alpha_pattern": {},
        "target_modules": list(MODULES),
    }
    (source / "adapter_config.json").write_text(json.dumps({**base, **config}))
    return source, file_sha256(source / "adapter_model.safetensors")


def _read_matrix(path: Path, key: str) -> tuple[tuple[int, ...], list[float]]:
    table, data_start = read_safetensors_header(path)
    entry = table[key]
    raw = path.read_bytes()[data_start + entry.start : data_start + entry.end]
    values = array("f")
    values.frombytes(raw)
    return entry.shape, list(values)


def test_converts_names_transposes_and_scale(tmp_path: Path) -> None:
    source, sha = _peft_dir(tmp_path)
    out = tmp_path / "mlx"

    attestation = convert_peft_lora_to_mlx(source, out, expected_source_sha256=sha)

    config = json.loads((out / "adapter_config.json").read_text())
    assert config == {
        "fine_tune_type": "lora",
        "num_layers": 2,
        "lora_parameters": {
            "rank": RANK,
            "scale": ALPHA / RANK,
            "dropout": 0.0,
            "keys": [
                "mlp.down_proj",
                "mlp.gate_proj",
                "self_attn.k_proj",
                "self_attn.o_proj",
                "self_attn.q_proj",
                "mlp.up_proj",
                "self_attn.v_proj",
            ],
        },
    }
    table, _ = read_safetensors_header(out / "adapters.safetensors")
    assert len(table) == 2 * 7 * 2
    peft = _peft_tensors()
    for layer in range(2):
        for module, (group, fan_in, fan_out) in MODULES.items():
            name = f"model.layers.{layer}.{group}.{module}"
            src = f"base_model.model.model.layers.{layer}.{group}.{module}"
            (a_shape, a), (b_shape, b) = (
                _read_matrix(out / "adapters.safetensors", f"{name}.lora_a"),
                _read_matrix(out / "adapters.safetensors", f"{name}.lora_b"),
            )
            assert a_shape == (fan_in, RANK) and b_shape == (RANK, fan_out)
            peft_a = peft[f"{src}.lora_A.weight"][1]
            peft_b = peft[f"{src}.lora_B.weight"][1]
            # mlx lora_a[i][r] == peft A[r][i]; mlx lora_b[r][o] == peft B[o][r]
            assert all(
                a[i * RANK + r] == peft_a[r * fan_in + i]
                for i in range(fan_in)
                for r in range(RANK)
            )
            assert all(
                b[r * fan_out + o] == peft_b[o * RANK + r]
                for r in range(RANK)
                for o in range(fan_out)
            )
    assert attestation.lora_layers == 14
    assert attestation.tensor_count == 28
    assert attestation.scale == 2.0
    assert attestation.expected_lora_modules() == {
        f"model.layers.{layer}.{group}.{module}"
        for layer in range(2)
        for module, (group, _, _) in MODULES.items()
    }


def test_attestation_is_stable_and_order_independent(tmp_path: Path) -> None:
    source, sha = _peft_dir(tmp_path)
    first = convert_peft_lora_to_mlx(source, tmp_path / "a", expected_source_sha256=sha)
    second = convert_peft_lora_to_mlx(
        source, tmp_path / "b", expected_source_sha256=sha
    )
    assert first == second

    reordered = tmp_path / "reordered"
    reordered.mkdir()
    tensors = _peft_tensors()
    _write(reordered / "adapter_model.safetensors", dict(reversed(tensors.items())))
    original = tensor_content_fingerprint(source / "adapter_model.safetensors")
    assert tensor_content_fingerprint(reordered / "adapter_model.safetensors") == (
        original
    )
    assert file_sha256(reordered / "adapter_model.safetensors") != sha

    round_trip = ConversionAttestation.from_dict(first.to_dict())
    assert round_trip == first
    verify_mlx_adapter(tmp_path / "a", first)


def test_refuses_wrong_source_hash(tmp_path: Path) -> None:
    source, _ = _peft_dir(tmp_path)
    with pytest.raises(ValueError, match="expected sha256"):
        convert_peft_lora_to_mlx(source, tmp_path / "out", expected_source_sha256="0")


def test_refuses_unknown_tensor_name(tmp_path: Path) -> None:
    tensors = _peft_tensors()
    tensors["base_model.model.model.layers.0.mlp.gate_proj.lora_magnitude"] = (
        (1,),
        [1.0],
    )
    source, sha = _peft_dir(tmp_path, tensors)
    with pytest.raises(ValueError, match="unexpected PEFT tensor name"):
        convert_peft_lora_to_mlx(source, tmp_path / "out", expected_source_sha256=sha)


def test_refuses_module_in_wrong_group(tmp_path: Path) -> None:
    tensors = _peft_tensors()
    key = "base_model.model.model.layers.1.self_attn.q_proj.lora_A.weight"
    tensors[key.replace("self_attn", "mlp")] = tensors.pop(key)
    source, sha = _peft_dir(tmp_path, tensors)
    with pytest.raises(ValueError, match="unexpected PEFT tensor name"):
        convert_peft_lora_to_mlx(source, tmp_path / "out", expected_source_sha256=sha)


def test_refuses_missing_tensor(tmp_path: Path) -> None:
    tensors = _peft_tensors()
    del tensors["base_model.model.model.layers.1.self_attn.v_proj.lora_B.weight"]
    source, sha = _peft_dir(tmp_path, tensors)
    with pytest.raises(ValueError, match="missing LoRA tensors"):
        convert_peft_lora_to_mlx(source, tmp_path / "out", expected_source_sha256=sha)


def test_refuses_rank_mismatch_and_unsupported_config(tmp_path: Path) -> None:
    source, sha = _peft_dir(tmp_path, r=RANK + 1)
    with pytest.raises(ValueError, match="rank"):
        convert_peft_lora_to_mlx(source, tmp_path / "out", expected_source_sha256=sha)
    for setting in ({"use_dora": True}, {"use_rslora": True}, {"bias": "all"}):
        other = tmp_path / next(iter(setting))
        other.mkdir()
        source, sha = _peft_dir(other, **setting)
        with pytest.raises(ValueError, match="unsupported PEFT adapter setting"):
            convert_peft_lora_to_mlx(source, other / "out", expected_source_sha256=sha)


def test_verify_refuses_a_changed_tensor(tmp_path: Path) -> None:
    source, sha = _peft_dir(tmp_path)
    out = tmp_path / "mlx"
    attestation = convert_peft_lora_to_mlx(source, out, expected_source_sha256=sha)
    weights = out / "adapters.safetensors"
    data = bytearray(weights.read_bytes())
    data[-1] ^= 0x01
    weights.write_bytes(bytes(data))
    with pytest.raises(ValueError, match="tensors do not match"):
        verify_mlx_adapter(out, attestation)


def test_committed_attestation_binds_the_03c_adapter() -> None:
    """The committed hashes name the adapter the 03C run manifest recorded."""

    attestation = load_attestation(ATTESTATION)
    manifest = json.loads(RUN_MANIFEST.read_text(encoding="utf-8"))
    assert (
        attestation.source_weights_sha256
        == (manifest["adapter_sha256"]["adapter_model.safetensors"])
    )
    assert attestation.source_config_sha256 == file_sha256(
        RUN_MANIFEST.parent / "adapter/adapter_config.json"
    )
    assert (attestation.num_layers, attestation.lora_layers) == (36, 252)
    assert attestation.tensor_count == 504
    assert (attestation.rank, attestation.alpha, attestation.scale) == (32, 64, 2.0)


def test_default_converted_adapter_path_is_git_ignored() -> None:
    for name in ("adapters.safetensors", "adapter_config.json"):
        result = subprocess.run(
            ["git", "check-ignore", "-q", f"{DEFAULT_MLX_ADAPTER}/{name}"],
            cwd=ROOT,
            check=False,
        )
        assert result.returncode == 0, name
