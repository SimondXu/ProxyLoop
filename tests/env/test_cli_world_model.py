"""``--world-model`` and the per-role ``--<role>-model`` specs (S1-SYS-71):
``<endpoint>:<model_id>[@<effort>]``, refused at parse time when bad."""

from __future__ import annotations

import pytest

from proxyloop import cli
from proxyloop.contract.config import SessionConfig
from proxyloop.contract.llm import AdapterKind, ModelRef

REAL = AdapterKind.REAL_HTTP


def _cfg(*argv: str) -> SessionConfig:
    args = cli.build_parser().parse_args(["session", "--family", "f", *argv])
    return cli.live_config(args)


def _world(cfg: SessionConfig) -> tuple[ModelRef, ModelRef, ModelRef]:
    return cfg.world.ear, cfg.world.mouth, cfg.world.simuser


def test_no_flag_keeps_todays_world() -> None:  # W1
    today = ModelRef(
        kind=REAL,
        endpoint="openrouter",
        model_id="google/gemini-3.8-flash",  # S1-SYS-96: TeamRouter's Gemini hung
        reasoning_effort="low",
    )
    assert _world(_cfg()) == (today, today, today)
    assert cli.WORLD == "google/gemini-3.8-flash" and cli.WORLD_EFFORT == "low"
    medium = _cfg("--world-effort", "medium", "--mouth-effort", "high")
    assert [r.reasoning_effort for r in _world(medium)] == ["medium", "high", "medium"]
    assert {(r.endpoint, r.model_id) for r in _world(medium)} == {
        ("openrouter", "google/gemini-3.8-flash")
    }
    for name in ("session", "rep-chat"):  # the same default on both commands
        args = cli.build_parser().parse_args([name, "--family", "f"])
        assert _world(cli.live_config(args)) == (today, today, today)


def test_the_world_model_sets_every_role_and_a_role_model_one() -> None:  # W2
    x = ModelRef(
        kind=REAL, endpoint="openrouter", model_id="vendor/x", reasoning_effort="low"
    )
    assert _world(_cfg("--world-model", "openrouter:vendor/x@low")) == (x, x, x)
    cfg = _cfg(
        *("--world-model", "openrouter:vendor/x@low"),
        *("--ear-model", "relay:ear-model@minimal"),
    )
    ear = ModelRef(
        kind=REAL, endpoint="relay", model_id="ear-model", reasoning_effort="minimal"
    )
    assert _world(cfg) == (ear, x, x)
    only = _cfg("--simuser-model", "relay:u")  # the others keep today's
    assert (only.world.ear.endpoint, only.world.ear.model_id) == (
        "openrouter",
        "google/gemini-3.8-flash",
    )
    assert only.world.simuser == ModelRef(
        kind=REAL, endpoint="relay", model_id="u", reasoning_effort="low"
    )  # no @effort in the spec: --world-effort (its default)


def test_the_effort_precedence() -> None:  # W3
    spec = ("--world-model", "relay:m@medium")
    assert {r.reasoning_effort for r in _world(_cfg(*spec))} == {"medium"}
    beats_world = _cfg(*spec, "--world-effort", "high")  # @effort beats --world-effort
    assert {r.reasoning_effort for r in _world(beats_world)} == {"medium"}
    role = _cfg(*spec, "--world-effort", "high", "--ear-effort", "none")
    assert [r.reasoning_effort for r in _world(role)] == ["none", "medium", "medium"]
    bare = _cfg("--world-model", "relay:m", "--world-effort", "high")
    assert {r.reasoning_effort for r in _world(bare)} == {"high"}
    own = _cfg(*spec, "--mouth-model", "relay:n")  # a role spec replaces the whole spec
    assert [r.reasoning_effort for r in _world(own)] == ["medium", "low", "medium"]


@pytest.mark.parametrize(
    "bad",
    [
        "gemini-3.8-flash",  # no endpoint
        "nowhere:m",  # unknown endpoint
        "vllm:Qwen3.5-9B",  # the vLLM adapter serves no world role
        "teamrouter:",  # empty model
        "teamrouter:@low",  # empty model, with an effort
        "teamrouter:m@turbo",  # bad effort
        "teamrouter:m@",  # empty effort
        ":m",  # empty endpoint
    ],
)
@pytest.mark.parametrize("flag", ["--world-model", "--ear-model", "--simuser-model"])
def test_a_bad_spec_is_an_argparse_error(
    bad: str, flag: str, capsys: pytest.CaptureFixture[str]
) -> None:  # W4
    with pytest.raises(SystemExit) as exit_:
        cli.main(["session", "--family", "f", flag, bad])
    assert exit_.value.code == 2
    assert f"argument {flag}" in capsys.readouterr().err


def test_a_model_id_may_hold_a_colon() -> None:  # W5
    cfg = _cfg("--world-model", "openrouter:vendor/model:tag@high")
    assert {(r.endpoint, r.model_id, r.reasoning_effort) for r in _world(cfg)} == {
        ("openrouter", "vendor/model:tag", "high")
    }
    plain = _cfg("--world-model", "teamrouter:a:b:c")
    assert plain.world.mouth.model_id == "a:b:c"
    assert plain.world.mouth.reasoning_effort == "low"
