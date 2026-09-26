"""Kernel fixes from the failed S0-ROOT-05 live smokes (S0-SYS-07): TTFS (l),
HOLD relay dedupe (e) and stale rep replies (i)."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from tests.kernel.test_session import SCRIPTS, UNTIL
from tests.support.sessions import only_bundle, run

from proxyloop.contract.events import Event


def _of(events: tuple[Event, ...], type_: str, lane: str = "cp") -> list[Event]:
    return [e for e in events if e.type == type_ and e.payload.get("lane") == lane]


def test_ttfs_is_set_when_the_only_sentence_is_released_at_close(
    tmp_path: Path,
) -> None:  # (l): a one-sentence reply closes only at parser.close()
    last = "@slow: fact monthly_price=75.00\nCould you lower the monthly price?"
    run(tmp_path, SCRIPTS | {"fast_cp": [last]}, until=UNTIL)
    turns = _of(only_bundle(tmp_path).events, "fast.turn")
    assert turns
    for turn in turns:
        items = cast(list[dict[str, object]], turn.payload["items"])
        assert [i["kind"] for i in items] == ["relay", "speech"]
        assert turn.payload["ttfs_ms"] is not None, turn.payload
