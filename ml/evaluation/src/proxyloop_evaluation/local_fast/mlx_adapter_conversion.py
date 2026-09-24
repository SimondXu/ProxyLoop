"""PEFT LoRA adapter -> ``mlx_lm`` LoRA adapter, with a content attestation.

``mlx_lm`` 0.31.3 loads only its own adapter format: ``adapter_config.json``
with ``fine_tune_type``/``num_layers``/``lora_parameters`` and
``adapters.safetensors`` holding ``model.layers.N.<group>.<module>.lora_a``
shaped ``(in, r)`` and ``lora_b`` shaped ``(r, out)``; the forward pass is
``y + scale * (x @ lora_a) @ lora_b``.  PEFT stores ``lora_A.weight`` as
``(r, in)`` and ``lora_B.weight`` as ``(out, r)`` with ``scale = alpha / r``,
so the conversion is a transpose and a rename; no value is rounded.

The safetensors container is read and written with the standard library so
the converter has no new dependency (the ml lock is frozen) and CI, which has
no MLX, runs it on real bytes.  Only little-endian F32 tensors are accepted:
the Phase 03C adapter is F32 and nothing else is needed.

The attestation fingerprints tensor *content* (sorted key, dtype, shape,
sha256 of the bytes), so it does not depend on the container's key order.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Final

CONVERTER_VERSION: Final = "phase-03c-peft-to-mlx-lora-v1"
ATTESTATION_SCHEMA_VERSION: Final = "phase-03c-mlx-adapter-attestation-v1"
PEFT_WEIGHTS: Final = "adapter_model.safetensors"
PEFT_CONFIG: Final = "adapter_config.json"
MLX_WEIGHTS: Final = "adapters.safetensors"
MLX_CONFIG: Final = "adapter_config.json"

# module -> the Qwen3 block attribute that owns it in mlx_lm.
MODULE_GROUPS: Final[dict[str, str]] = {
    "q_proj": "self_attn",
    "k_proj": "self_attn",
    "v_proj": "self_attn",
    "o_proj": "self_attn",
    "gate_proj": "mlp",
    "up_proj": "mlp",
    "down_proj": "mlp",
}
_PEFT_KEY: Final = re.compile(
    r"^base_model\.model\.model\.layers\.(?P<layer>0|[1-9][0-9]*)\."
    r"(?P<group>self_attn|mlp)\.(?P<module>[a-z_]+)\.lora_(?P<side>[AB])\.weight$"
)
_HEADER_LIMIT: Final = 100 * 1024 * 1024
_F32: Final = "F32"


@dataclass(frozen=True, slots=True)
class TensorEntry:
    dtype: str
    shape: tuple[int, ...]
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ConversionAttestation:
    """What a conversion produced, as hashes and counts only (no paths)."""

    source_weights_sha256: str
    source_config_sha256: str
    content_fingerprint: str
    mlx_config_sha256: str
    num_layers: int
    lora_layers: int
    tensor_count: int
    rank: int
    alpha: int
    scale: float
    keys: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": ATTESTATION_SCHEMA_VERSION,
            "converter_version": CONVERTER_VERSION,
            "source": {
                "format": "peft-lora",
                "weights_sha256": self.source_weights_sha256,
                "config_sha256": self.source_config_sha256,
            },
            "output": {
                "format": "mlx-lm-lora",
                "content_fingerprint": self.content_fingerprint,
                "config_sha256": self.mlx_config_sha256,
                "dtype": _F32,
                "num_layers": self.num_layers,
                "lora_layers": self.lora_layers,
                "tensor_count": self.tensor_count,
                "rank": self.rank,
                "alpha": self.alpha,
                "scale": self.scale,
                "keys": list(self.keys),
            },
        }

    @classmethod
    def from_dict(cls, value: object) -> ConversionAttestation:
        if not isinstance(value, dict):
            raise ValueError("attestation must be a JSON object")
        if (
            value.get("schema_version") != ATTESTATION_SCHEMA_VERSION
            or value.get("converter_version") != CONVERTER_VERSION
        ):
            raise ValueError("attestation schema or converter version differs")
        source, output = value["source"], value["output"]
        attestation = cls(
            source_weights_sha256=str(source["weights_sha256"]),
            source_config_sha256=str(source["config_sha256"]),
            content_fingerprint=str(output["content_fingerprint"]),
            mlx_config_sha256=str(output["config_sha256"]),
            num_layers=int(output["num_layers"]),
            lora_layers=int(output["lora_layers"]),
            tensor_count=int(output["tensor_count"]),
            rank=int(output["rank"]),
            alpha=int(output["alpha"]),
            scale=float(output["scale"]),
            keys=tuple(str(item) for item in output["keys"]),
        )
        if attestation.to_dict() != value:
            raise ValueError("attestation has unexpected or non-canonical fields")
        return attestation

    def expected_lora_modules(self) -> frozenset[str]:
        """Module paths ``mlx_lm`` must turn into loaded LoRA layers."""

        return frozenset(
            f"model.layers.{layer}.{key}"
            for layer in range(self.num_layers)
            for key in self.keys
        )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_safetensors_header(path: Path) -> tuple[dict[str, TensorEntry], int]:
    """Tensor table and the absolute offset where tensor data starts."""

    with path.open("rb") as stream:
        prefix = stream.read(8)
        if len(prefix) != 8:
            raise ValueError("safetensors file is truncated")
        (size,) = struct.unpack("<Q", prefix)
        if size > _HEADER_LIMIT:
            raise ValueError("safetensors header is too large")
        raw = stream.read(size)
    if len(raw) != size:
        raise ValueError("safetensors header is truncated")
    header = json.loads(raw)
    if not isinstance(header, dict):
        raise ValueError("safetensors header must be a JSON object")
    header.pop("__metadata__", None)
    table: dict[str, TensorEntry] = {}
    for key, entry in header.items():
        start, end = entry["data_offsets"]
        table[key] = TensorEntry(
            dtype=str(entry["dtype"]),
            shape=tuple(int(item) for item in entry["shape"]),
            start=int(start),
            end=int(end),
        )
    return table, 8 + size


def _read_tensor(path: Path, entry: TensorEntry, data_start: int) -> bytes:
    with path.open("rb") as stream:
        stream.seek(data_start + entry.start)
        data = stream.read(entry.end - entry.start)
    if len(data) != entry.end - entry.start:
        raise ValueError("safetensors tensor data is truncated")
    return data


def tensor_content_fingerprint(path: Path) -> str:
    """sha256 over sorted ``(key, dtype, shape, sha256(bytes))`` rows."""

    table, data_start = read_safetensors_header(path)
    rows = [
        [
            key,
            entry.dtype,
            list(entry.shape),
            hashlib.sha256(_read_tensor(path, entry, data_start)).hexdigest(),
        ]
        for key, entry in sorted(table.items())
    ]
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _transpose_f32(data: bytes, rows: int, cols: int) -> bytes:
    """Row-major ``(rows, cols)`` F32 -> row-major ``(cols, rows)``."""

    source = array("f")
    source.frombytes(data)
    if len(source) != rows * cols:
        raise ValueError("tensor byte length does not match its shape")
    out = array("f", bytes(len(data)))
    for row in range(rows):
        out[row::rows] = source[row * cols : (row + 1) * cols]
    return out.tobytes()


def _write_safetensors(
    path: Path, tensors: dict[str, tuple[tuple[int, ...], bytes]]
) -> None:
    header: dict[str, object] = {"__metadata__": {"format": "mlx"}}
    offset = 0
    for key in sorted(tensors):
        shape, data = tensors[key]
        header[key] = {
            "dtype": _F32,
            "shape": list(shape),
            "data_offsets": [offset, offset + len(data)],
        }
        offset += len(data)
    encoded = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 8)
    with path.open("wb") as stream:
        stream.write(struct.pack("<Q", len(encoded)))
        stream.write(encoded)
        for key in sorted(tensors):
            stream.write(tensors[key][1])


def _peft_lora_config(path: Path) -> tuple[int, int, tuple[str, ...]]:
    """``(rank, alpha, target_modules)`` of a plain PEFT LoRA config."""

    config = json.loads(path.read_text(encoding="utf-8"))
    plain = {
        "peft_type": "LORA",
        "bias": "none",
        "fan_in_fan_out": False,
        "use_dora": False,
        "use_rslora": False,
        "layers_to_transform": None,
        "modules_to_save": None,
        "rank_pattern": {},
        "alpha_pattern": {},
    }
    for key, expected in plain.items():
        if config.get(key) != expected:
            raise ValueError(f"unsupported PEFT adapter setting: {key}")
    rank, alpha = config.get("r"), config.get("lora_alpha")
    if type(rank) is not int or type(alpha) is not int or rank < 1 or alpha < 1:
        raise ValueError("PEFT adapter r and lora_alpha must be positive integers")
    modules = tuple(sorted(config.get("target_modules") or ()))
    if not modules or not set(modules) <= MODULE_GROUPS.keys():
        raise ValueError("PEFT target_modules must be known Qwen3 projections")
    return rank, alpha, modules


def convert_peft_lora_to_mlx(
    source: Path, destination: Path, *, expected_source_sha256: str
) -> ConversionAttestation:
    """Convert ``source`` (a PEFT adapter dir) into ``destination``.

    Refuses a source whose weights hash differs from ``expected_source_sha256``,
    any tensor name outside the PEFT LoRA pattern for the configured modules,
    a missing ``A``/``B`` pair in any layer, a non-F32 tensor, and a shape that
    disagrees with the configured rank.
    """

    if sys.byteorder != "little":
        raise RuntimeError("safetensors conversion requires a little-endian host")
    weights = source / PEFT_WEIGHTS
    config_path = source / PEFT_CONFIG
    source_sha = file_sha256(weights)
    if source_sha != expected_source_sha256:
        raise ValueError("PEFT adapter weights do not match the expected sha256")
    rank, alpha, modules = _peft_lora_config(config_path)
    table, data_start = read_safetensors_header(weights)

    found: dict[tuple[int, str, str], TensorEntry] = {}
    for key, entry in table.items():
        match = _PEFT_KEY.match(key)
        if match is None:
            raise ValueError(f"unexpected PEFT tensor name: {key}")
        module = match["module"]
        if module not in modules or MODULE_GROUPS[module] != match["group"]:
            raise ValueError(f"unexpected PEFT tensor name: {key}")
        if entry.dtype != _F32:
            raise ValueError(f"PEFT tensor {key} must be F32")
        if len(entry.shape) != 2:
            raise ValueError(f"PEFT tensor {key} must be a matrix")
        side_rank = entry.shape[0] if match["side"] == "A" else entry.shape[1]
        if side_rank != rank:
            raise ValueError(f"PEFT tensor {key} does not have rank {rank}")
        found[(int(match["layer"]), module, match["side"])] = entry

    num_layers = 1 + max((layer for layer, _, _ in found), default=-1)
    expected = {
        (layer, module, side)
        for layer in range(num_layers)
        for module in modules
        for side in ("A", "B")
    }
    if num_layers == 0 or set(found) != expected:
        raise ValueError("PEFT adapter is missing LoRA tensors for some layers")

    tensors: dict[str, tuple[tuple[int, ...], bytes]] = {}
    for (layer, module, side), entry in found.items():
        rows, cols = entry.shape
        name = f"model.layers.{layer}.{MODULE_GROUPS[module]}.{module}.lora_"
        name += "a" if side == "A" else "b"
        data = _read_tensor(weights, entry, data_start)
        tensors[name] = ((cols, rows), _transpose_f32(data, rows, cols))

    keys = tuple(f"{MODULE_GROUPS[module]}.{module}" for module in modules)
    mlx_config = {
        "fine_tune_type": "lora",
        "num_layers": num_layers,
        "lora_parameters": {
            "rank": rank,
            "scale": alpha / rank,
            "dropout": 0.0,
            "keys": list(keys),
        },
    }
    destination.mkdir(parents=True, exist_ok=True)
    _write_safetensors(destination / MLX_WEIGHTS, tensors)
    (destination / MLX_CONFIG).write_text(
        json.dumps(mlx_config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return ConversionAttestation(
        source_weights_sha256=source_sha,
        source_config_sha256=file_sha256(config_path),
        content_fingerprint=tensor_content_fingerprint(destination / MLX_WEIGHTS),
        mlx_config_sha256=file_sha256(destination / MLX_CONFIG),
        num_layers=num_layers,
        lora_layers=num_layers * len(modules),
        tensor_count=len(tensors),
        rank=rank,
        alpha=alpha,
        scale=alpha / rank,
        keys=keys,
    )


def verify_mlx_adapter(path: Path, attestation: ConversionAttestation) -> None:
    """Refuse an MLX adapter dir whose content differs from ``attestation``."""

    if file_sha256(path / MLX_CONFIG) != attestation.mlx_config_sha256:
        raise ValueError("MLX adapter config does not match the attestation")
    if tensor_content_fingerprint(path / MLX_WEIGHTS) != (
        attestation.content_fingerprint
    ):
        raise ValueError("MLX adapter tensors do not match the attestation")


def load_attestation(path: Path) -> ConversionAttestation:
    return ConversionAttestation.from_dict(json.loads(path.read_text(encoding="utf-8")))


def render_attestation(attestation: ConversionAttestation) -> str:
    return json.dumps(attestation.to_dict(), indent=2, sort_keys=True) + "\n"


__all__ = [
    "ATTESTATION_SCHEMA_VERSION",
    "CONVERTER_VERSION",
    "ConversionAttestation",
    "convert_peft_lora_to_mlx",
    "file_sha256",
    "load_attestation",
    "read_safetensors_header",
    "render_attestation",
    "tensor_content_fingerprint",
    "verify_mlx_adapter",
]
