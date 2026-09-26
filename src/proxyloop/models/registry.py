"""Models and Fast conditions by name (EVAL §4.1; data in ``conditions.yaml``).

``resolve(name)`` gives a model's ``ModelRef``; ``lanes(fast_user, fast_cp)``
is a per-lane choice by model name. ``condition(name).apply(cfg)`` sets a
condition's Fast lanes, teacher and ablations on a ``SessionConfig`` and
re-validates it (I1: a condition is a config value, never a second runner).
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path

import yaml
from pydantic import Field

from proxyloop.contract.base import Frozen
from proxyloop.contract.config import AblationId, SessionConfig
from proxyloop.contract.llm import AdapterKind, LLMClient, ModelRef
from proxyloop.models.repair import TeacherRepair

CONDITIONS = Path(__file__).with_name("conditions.yaml")
TRAINED = "qwen3.5-9b-sft"  # C1: the base 9B plus the served trained LoRA slot


class _Spec(Frozen):
    fast_user: str
    fast_cp: str
    teacher: str | None = None
    ablations: tuple[AblationId, ...] = ()
    teacher_resamples: int | None = Field(default=None, ge=0)


class _File(Frozen):
    models: dict[str, ModelRef]
    conditions: dict[str, _Spec]


class Condition(Frozen):
    name: str
    fast_user: ModelRef
    fast_cp: ModelRef
    teacher: ModelRef | None = None
    ablations: tuple[AblationId, ...] = ()
    teacher_resamples: int | None = Field(default=None, ge=0)

    def teacher_repair(self, teacher: LLMClient) -> TeacherRepair:
        """The teacher's client under this condition's resample limit (T, R)."""

        if self.teacher_resamples is None:
            raise ValueError(f"{self.name} runs no teacher as a Fast")
        return TeacherRepair(teacher, max_resamples=self.teacher_resamples)

    def apply(self, cfg: SessionConfig) -> SessionConfig:
        """``cfg`` with this condition's Fast lanes; ablations are merged."""

        if None not in (cfg.teacher, self.teacher) and cfg.teacher != self.teacher:
            raise ValueError(f"{self.name} names a teacher other than the cfg's")
        data = cfg.model_dump()
        data |= {"fast_user": self.fast_user, "fast_cp": self.fast_cp}
        data |= {"teacher": self.teacher or cfg.teacher}
        data |= {"ablations": (*cfg.ablations, *self.ablations)}
        return SessionConfig.model_validate(data)


@cache
def _load() -> _File:
    return _File.model_validate(yaml.safe_load(CONDITIONS.read_text("utf-8")))


def models() -> tuple[str, ...]:
    return (*_load().models, TRAINED)


def conditions() -> tuple[str, ...]:
    return tuple(_load().conditions)


def trained(spec: str | None = None) -> ModelRef:
    """C1's Fast: the trained slot named by serving's ``PL_TRAINED_ADAPTER``
    ("<name>=<path>", the one the server was deployed with; ``spec`` overrides
    the environment). Unset means no C1, never base Qwen (AGENTS rule 6)."""

    from serving import config  # top-level MOD package: run from the repo root

    spec = os.environ.get(config.TRAINED_ENV, "") if spec is None else spec
    slot = config.trained_slot(spec, "")  # checks the TRAINED_PREFIX name
    if not slot:
        raise LookupError(f"{TRAINED} needs {config.TRAINED_ENV}=<name>=<path>")
    (name,) = slot
    return ModelRef(kind=AdapterKind.REAL_HTTP, endpoint="vllm", model_id=name)


def resolve(name: str) -> ModelRef:
    if name == TRAINED:
        return trained()
    found = _load().models.get(name)
    if found is None:
        raise KeyError(f"unknown model {name!r}; known: {', '.join(models())}")
    return found


def condition(name: str) -> Condition:
    spec = _load().conditions.get(name)
    if spec is None:
        raise KeyError(f"unknown condition {name!r}; known: {', '.join(conditions())}")
    teacher = None if spec.teacher is None else resolve(spec.teacher)
    return Condition(
        name=name,
        fast_user=resolve(spec.fast_user),
        fast_cp=resolve(spec.fast_cp),
        teacher=teacher,
        ablations=spec.ablations,
        teacher_resamples=spec.teacher_resamples,
    )


def lanes(fast_user: str, fast_cp: str) -> Condition:
    """A per-lane Fast choice by model name (e.g. EVAL A3's lane swap). It names
    no teacher, so it runs no ``TeacherRepair``: T and R are named conditions."""

    return Condition(
        name=f"{fast_user}/{fast_cp}",
        fast_user=resolve(fast_user),
        fast_cp=resolve(fast_cp),
    )
