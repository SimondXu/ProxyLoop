"""S1-SYS-14: ``--condition`` builds a condition's Fast lanes from ``ModelRef``
ids (EVAL §4.1), held here to the MOD registry's ``conditions.yaml``."""

from __future__ import annotations

from typing import Any

import pytest
from tests.llm.wire import counter_clock

from proxyloop import cli
from proxyloop.contract.config import AblationId, SessionConfig, config_hash
from proxyloop.contract.llm import AdapterKind
from proxyloop.llm.factory import LiveModeError, make_client
from proxyloop.llm.relay import ChatClient
from proxyloop.models import registry
from proxyloop.models.fsm import FsmTalker


def _cfg(*argv: str) -> SessionConfig:
    return cli.live_config(
        cli.build_parser().parse_args(["session", "--family", "f", *argv])
    )


def test_the_cli_conditions_are_the_registrys() -> None:
    """Every named condition but C1 (a deployed slot) sets what the registry's
    ``condition(name).apply`` sets on the CLI's default config."""
    assert set(cli.CONDITIONS) == set(registry.conditions()) - {"C1"}
    for name in cli.CONDITIONS:
        cfg = _cfg("--condition", name)
        assert cfg.live is (name != "F")  # F is a non-live run (AGENTS rule 5)
        want = registry.condition(name).apply(_cfg())
        assert cfg == want.model_copy(update={"live": cfg.live})


def test_f_builds_the_fsm_on_both_lanes_in_a_non_live_cfg() -> None:
    cfg = _cfg("--condition", "F")
    assert cfg.fast_user == cfg.fast_cp == cli.FSM
    assert cfg.fast_cp.kind is AdapterKind.BASELINE
    assert (cfg.teacher, cfg.ablations, cfg.live) == (None, (), False)
    assert config_hash(cfg) != config_hash(cfg.model_copy(update={"live": True}))
    fsm = make_client(cfg.fast_cp, live=False, clock=counter_clock(), on_record=print)
    assert isinstance(fsm, FsmTalker)
    with pytest.raises(LiveModeError):
        make_client(cfg.fast_cp, live=True, clock=counter_clock(), on_record=print)


def test_t_is_the_teacher_as_fast_with_no_repair(monkeypatch: Any) -> None:
    cfg = _cfg("--condition", "T")
    assert cfg.fast_user == cfg.fast_cp == cli.SONNET
    assert (cfg.teacher, cfg.ablations) == (None, ())
    monkeypatch.setenv("PL_RELAY_BASE_URL", "https://relay.test")
    monkeypatch.setenv("PL_RELAY_API_KEY", "k")
    fast = make_client(cfg.fast_cp, live=True, clock=counter_clock(), on_record=print)
    assert isinstance(fast, ChatClient)


def test_r_repairs_the_student_with_the_teacher_on_both_lanes() -> None:
    cfg = _cfg("--condition", "R")
    assert cfg.fast_user == cfg.fast_cp == cli.QWEN9
    assert cfg.teacher == cli.SONNET
    repair = {AblationId.TEACHER_REPAIR_CP, AblationId.TEACHER_REPAIR_USER}
    assert set(cfg.ablations) == repair


def test_c5_is_luna_with_the_users_effort() -> None:
    fast = _cfg("--condition", "C5").fast_cp
    assert (fast.endpoint, fast.model_id, fast.reasoning_effort) == (
        "openrouter",
        "openai/gpt-6-luna",
        "none",
    )


@pytest.mark.parametrize(
    "extra",
    [
        ("--fast-model", "x"),
        ("--fast-endpoint", "relay"),
        ("--fast-endpoint", "openrouter", "--fast-effort", "low"),
    ],
)
def test_a_condition_refuses_its_own_fast_options(extra: tuple[str, ...]) -> None:
    argv = ["session", "--family", "f", "--condition", "C2", *extra]
    with pytest.raises(SystemExit):
        cli.main(argv)
