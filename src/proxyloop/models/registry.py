"""Models and Fast conditions by name (EVAL §4.1; data in ``conditions.yaml``).

``resolve(name)`` gives a model's ``ModelRef`` (per-lane choices use it);
``condition(name).apply(cfg)`` sets a condition's Fast lanes, teacher and
ablations on a ``SessionConfig`` and re-validates it (I1: a condition is a
config value, never a second runner).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

from proxyloop.contract.base import Frozen
from proxyloop.contract.config import AblationId, SessionConfig
from proxyloop.contract.llm import ModelRef

CONDITIONS = Path(__file__).with_name("conditions.yaml")


class _Spec(Frozen):
    fast_user: str
    fast_cp: str
    teacher: str | None = None
    ablations: tuple[AblationId, ...] = ()


class _File(Frozen):
    models: dict[str, ModelRef]
    conditions: dict[str, _Spec]


class Condition(Frozen):
    name: str
    fast_user: ModelRef
    fast_cp: ModelRef
    teacher: ModelRef | None = None
    ablations: tuple[AblationId, ...] = ()

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
    return tuple(_load().models)


def conditions() -> tuple[str, ...]:
    return tuple(_load().conditions)


def resolve(name: str) -> ModelRef:
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
    )
