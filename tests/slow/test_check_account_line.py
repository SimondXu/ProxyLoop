"""``check_account`` binds a rep line Slow read (ADR-0016, S1-SYS-34): the
confirmation id must be in the cited REP line (the relay's boundary rule) and
in the ledger; an agent line (a self-binding), another line, or an id the
ledger lacks is refused. ``relay_only`` ignores ``utt_ref`` (relays only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.slow.test_authority import BOUND, DONE, Host
from tests.slow.test_authority import (
    _accepted as accepted,  # pyright: ignore[reportPrivateUsage]
)
from tests.slow.test_authority import (
    _committed as committed,  # pyright: ignore[reportPrivateUsage]
)

from proxyloop.contract.events import Event
from proxyloop.contract.llm import ToolCall
from proxyloop.contract.state import CaseStatus

SAID = "Done, the offer is accepted. Your confirmation number is 482913."


def _confirmed_by_the_rep(h: Host, said: str = SAID, conf: str = "482913") -> Event:
    """The accept released and heard, the rep's confirmation line, the
    ledger's write; FastC relays nothing (the case Slow used to stall on)."""
    (line,) = [e for e in h.of("speak.verbatim") if e.payload["kind"] == "accept"]
    released = h.emit(
        "speak.released", "kernel", {"lane": "cp", "cap_id": line.payload["cap_id"]},
        [line.event_id],
    )  # fmt: skip
    heard = {"lane": "cp", "utt_id": "a-1", "text_generated": line.payload["text"]}
    heard |= {"text_heard": line.payload["text"], "interrupted": False}
    h.delivered = h.emit("utt.delivered", "kernel", heard, [released.event_id])
    committed(h)
    done = h.rep("cp-3", said)
    binding = {"offer_ref": "save-2", "revision": 1, "term_months": 24}
    write = {"confirmation_id": conf, "binding": binding | {"terms": BOUND}}
    h.emit("ledger.write", "world.ledger", write, [done.event_id], "world")
    return done


def check(conf: str = "482913", utt: str = "cp-3") -> dict[str, str]:
    return {"tool": "check_account", "confirmation_id": conf, "utt_ref": utt}


def test_a_rep_line_holding_the_id_binds_it(tmp_path: Path) -> None:
    h = accepted(tmp_path)
    done = _confirmed_by_the_rep(h)
    (unrelayed,) = h.act({"tool": "check_account", "confirmation_id": "482913"})
    assert "no such confirmation relayed" in unrelayed  # no relay, no line cited
    account, finished = h.act(check(), DONE)
    assert account == "check_account: 482913 binds the accepted terms"
    (evidence,) = h.of("evidence.recorded")
    (write,) = h.of("ledger.write")
    assert {write.event_id, done.event_id} <= set(evidence.cause_ids)
    assert finished == "finish: verified complete"
    assert h.bb.public.status is CaseStatus.VERIFIED_COMPLETE
    h.bus.close()


@pytest.mark.parametrize(
    ("said", "conf", "utt", "why"),
    [
        (SAID, "482913", "cp-1", "rep line cp-1 does not say '482913'"),  # the offer
        (SAID, "48291", "cp-3", "rep line cp-3 does not say '48291'"),  # boundary
        ("Your number is 4829135.", "482913", "cp-3", "does not say '482913'"),
        (SAID, "482913", "a-1", "'a-1' is no rep line"),  # the phone voice's own
        (SAID, "482913", "cp-9", "'cp-9' is no rep line"),  # no such line
    ],
)
def test_a_line_that_does_not_say_the_id_is_refused(
    tmp_path: Path, said: str, conf: str, utt: str, why: str
) -> None:
    h = accepted(tmp_path)
    _confirmed_by_the_rep(h, said)
    (account,) = h.act(check(conf, utt))
    assert why in account, account
    assert not h.of("evidence.recorded")
    assert h.bb.public.status is CaseStatus.COMMITTED
    h.bus.close()


def test_a_self_binding_agent_line_is_refused_even_if_it_says_the_id(
    tmp_path: Path,
) -> None:
    h = accepted(tmp_path)
    _confirmed_by_the_rep(h, "Okay, it is done.")  # the rep never says an id
    heard = {"lane": "cp", "utt_id": "a-2", "text_generated": "Is it 482913?"}
    h.emit("utt.delivered", "kernel", heard | {"text_heard": "Is it 482913?",
           "interrupted": False}, [h.root.event_id])  # fmt: skip
    (account,) = h.act(check(utt="a-2"))
    assert "'a-2' is no rep line" in account and not h.of("evidence.recorded")
    h.bus.close()


def test_an_id_the_ledger_lacks_is_refused(tmp_path: Path) -> None:
    h = accepted(tmp_path)
    _confirmed_by_the_rep(h, "Your confirmation number is 555111.", conf="999999")
    (account,) = h.act(check("555111"))
    assert account == "check_account: the account shows no confirmation 555111"
    assert not h.of("evidence.recorded")
    h.bus.close()


def test_relay_only_ignores_the_cited_line(tmp_path: Path) -> None:
    h = accepted(tmp_path)
    h.tools._transcript = False  # pyright: ignore[reportPrivateUsage]
    _confirmed_by_the_rep(h)
    (account,) = h.act(check())
    assert "no such confirmation relayed: '482913'" in account
    assert not h.of("evidence.recorded")
    h.bus.close()


def test_a_line_after_the_steps_view_is_refused(tmp_path: Path) -> None:
    """Review N2: Slow may cite only a line its step was shown (the line's
    seq at or before the step's basis)."""
    h = accepted(tmp_path)
    done = _confirmed_by_the_rep(h)
    body = json.dumps({"private_summary": "d", "calls": [check()]})
    call = ToolCall(call_id="c", name="act", arguments=body)
    early = h.tools.act(call, [h.root.event_id], basis=done.seq - 1)
    assert "rep line cp-3 came after your view" in early
    assert not h.of("evidence.recorded")
    seen = h.tools.act(call, [h.root.event_id], basis=done.seq)
    assert "482913 binds the accepted terms" in seen
    h.bus.close()


def test_the_last_line_with_the_cited_utt_id_is_the_one_checked(
    tmp_path: Path,
) -> None:
    """#183 review N-d: when an utt id repeats in the cp lane, the text check
    and the seq check read the same line, the last one."""
    h = accepted(tmp_path)
    h.rep("cp-3", "One moment please.")  # an earlier line with the same utt id
    _confirmed_by_the_rep(h)  # cp-3 again, saying the id
    (account,) = h.act(check())
    assert account == "check_account: 482913 binds the accepted terms", account
    h.bus.close()
