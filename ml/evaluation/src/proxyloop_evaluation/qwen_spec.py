"""Attestable local Qwen checkpoint identities for Phase 03C.

``qwen_mlx.py`` hard-codes the historical 4B 4-bit base and is bound by the
Phase 03A1 r4 execution contract, so the configurable checkpoint identity
lives here.  The 4B spec reproduces the historical constants exactly; the 8B
spec pins the official MLX bf16 export observed on 2026-09-21.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .qwen_mlx import (
    QWEN_CHAT_TEMPLATE_FINGERPRINT,
    QWEN_CHECKPOINT_FINGERPRINT,
    QWEN_MLX_MODEL,
    QWEN_MODEL_REVISION,
    QWEN_QUANTIZATION,
    QWEN_RUN_LABEL,
    QWEN_SOURCE_LINEAGE,
    QWEN_SOURCE_REVISION,
    QWEN_TOKENIZER_FINGERPRINT,
    QWEN_TUNING,
    QwenCheckpointAttestation,
)

THINKING_OPEN_TAG = "<think>"


@dataclass(frozen=True, slots=True)
class QwenModelSpec:
    """One frozen local checkpoint identity the adapter may attest and load.

    ``enable_thinking`` is ``None`` for checkpoints whose chat template has no
    thinking switch (the historical 4B Instruct base) and ``False`` for hybrid
    thinking models, where the switch must be passed on every render.
    """

    model: str
    source_lineage: str
    run_label: str
    quantization: str
    tuning: str
    model_revision: str
    source_revision: str
    checkpoint_fingerprint: str
    tokenizer_fingerprint: str
    chat_template_fingerprint: str
    enable_thinking: bool | None = None
    license: str | None = None

    @property
    def attestation(self) -> QwenCheckpointAttestation:
        return QwenCheckpointAttestation(
            model_revision=self.model_revision,
            source_revision=self.source_revision,
            checkpoint_fingerprint=self.checkpoint_fingerprint,
            tokenizer_fingerprint=self.tokenizer_fingerprint,
            chat_template_fingerprint=self.chat_template_fingerprint,
        )


QWEN3_4B_4BIT_SPEC = QwenModelSpec(
    model=QWEN_MLX_MODEL,
    source_lineage=QWEN_SOURCE_LINEAGE,
    run_label=QWEN_RUN_LABEL,
    quantization=QWEN_QUANTIZATION,
    tuning=QWEN_TUNING,
    model_revision=QWEN_MODEL_REVISION,
    source_revision=QWEN_SOURCE_REVISION,
    checkpoint_fingerprint=QWEN_CHECKPOINT_FINGERPRINT,
    tokenizer_fingerprint=QWEN_TOKENIZER_FINGERPRINT,
    chat_template_fingerprint=QWEN_CHAT_TEMPLATE_FINGERPRINT,
    enable_thinking=None,
    license="apache-2.0",
)

# Official Qwen MLX export of the hybrid thinking model.  Fingerprints were
# observed with ``observe_qwen_snapshot`` on 2026-09-21 and are recorded in
# ``harness/context/phase-03c-preflight.md``.
QWEN3_8B_BF16_SPEC = QwenModelSpec(
    model="Qwen/Qwen3-8B-MLX-bf16",
    source_lineage="Qwen/Qwen3-8B",
    run_label="bf16_untuned",
    quantization="bf16",
    tuning="untuned",
    model_revision="6766fd4b8101fa4201cc55c5a2e464f3d301f792",
    source_revision="b968826d9c46dd6066d109eabc6255188de91218",
    checkpoint_fingerprint=(
        "9dc231054f911dfc2f83cdbacf1925ce0f86e15e22e42b369794c0a6668c80cd"
    ),
    tokenizer_fingerprint=(
        "bc73b4d7e1c6615d001b2f9ed981d6f1393a6899b4294e264c2b3bbf3f3ab035"
    ),
    chat_template_fingerprint=(
        "57f1fd00f0013a2be96aa79b857391f27e23df5b5f847072b524c897e24d0361"
    ),
    enable_thinking=False,
    license="apache-2.0",
)

_TOKENIZER_NAMES = frozenset(
    {
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.json",
        "merges.txt",
        "added_tokens.json",
        "special_tokens_map.json",
    }
)


def _object_fingerprint(value: object) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _chat_template_fingerprint(
    snapshot: Path, rows: Mapping[str, Mapping[str, object]]
) -> str:
    """Prefer a standalone template file; otherwise hash the embedded string."""

    if "chat_template.jinja" in rows:
        return str(rows["chat_template.jinja"]["sha256"])
    config = json.loads((snapshot / "tokenizer_config.json").read_text("utf-8"))
    template = config.get("chat_template") if isinstance(config, dict) else None
    if not isinstance(template, str) or not template:
        raise ValueError("Qwen snapshot has no chat template to attest")
    return hashlib.sha256(template.encode("utf-8")).hexdigest()


def observe_qwen_snapshot(model_path: str) -> QwenCheckpointAttestation:
    """Hash a local snapshot directory without comparing it to a spec.

    Used once per checkpoint to pin a new ``QwenModelSpec``.  Sharded
    ``*.safetensors`` and a template embedded in ``tokenizer_config.json`` are
    accepted, so the historical single-file 4B snapshot reproduces its
    frozen fingerprints and the official 8B export can be attested too.
    ``source_revision`` is empty: files cannot attest their upstream lineage.
    """

    snapshot = Path(model_path)
    if not snapshot.is_dir():
        raise ValueError("Qwen model path is not a snapshot directory")
    rows: dict[str, dict[str, object]] = {}
    for path in sorted(snapshot.iterdir(), key=lambda item: item.name):
        if path.name.startswith(".") or not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        rows[path.name] = {"sha256": digest.hexdigest(), "size": path.stat().st_size}
    required = {"config.json", "tokenizer.json", "tokenizer_config.json"}
    if not required <= rows.keys() or not any(
        name.endswith(".safetensors") for name in rows
    ):
        raise ValueError("Qwen snapshot is missing required model/tokenizer files")
    return QwenCheckpointAttestation(
        model_revision=snapshot.name,
        source_revision="",
        checkpoint_fingerprint=_object_fingerprint(rows),
        tokenizer_fingerprint=_object_fingerprint(
            {name: rows[name] for name in sorted(_TOKENIZER_NAMES) if name in rows}
        ),
        chat_template_fingerprint=_chat_template_fingerprint(snapshot, rows),
    )


def attest_qwen_spec(model_path: str, spec: QwenModelSpec) -> QwenCheckpointAttestation:
    """Hash the actual local snapshot and require it to match ``spec``."""

    snapshot = Path(model_path)
    if not snapshot.is_dir() or snapshot.name != spec.model_revision:
        raise ValueError("Qwen model path is not the frozen snapshot revision")
    observed = observe_qwen_snapshot(model_path)
    if (
        observed.checkpoint_fingerprint,
        observed.tokenizer_fingerprint,
        observed.chat_template_fingerprint,
    ) != (
        spec.checkpoint_fingerprint,
        spec.tokenizer_fingerprint,
        spec.chat_template_fingerprint,
    ):
        raise ValueError("Qwen checkpoint attestation does not match the frozen files")
    return spec.attestation


__all__ = [
    "QWEN3_4B_4BIT_SPEC",
    "QWEN3_8B_BF16_SPEC",
    "THINKING_OPEN_TAG",
    "QwenModelSpec",
    "attest_qwen_spec",
    "observe_qwen_snapshot",
]
