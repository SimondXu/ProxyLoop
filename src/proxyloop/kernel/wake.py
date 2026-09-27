"""When Slow wakes (ARCHITECTURE §11, S1-SYS-29): a bus subscriber, like
``kernel.fence.Authority``, holding the kernel's one Slow timer. ``SlowLoop``
takes one step at a time; wakes that arrive during a step merge into the next.

Every wake source, by its fixed reason (never text):
- here: ``relay`` (``f2s.msg``); while the cp call is open (``chan.opened{cp}``
  to ``chan.closed{cp}``) ``rep_turn`` (a partner ``utt.final``, below) and
  ``strike`` (``chan.strike``); ``call_closed`` (``chan.closed{cp}``); ``timer``
  and ``heartbeat`` (below);
- in ``kernel.fence.Authority``: ``fence`` (a ``user.msg`` fence is bound),
  ``replan`` (NEEDS_REPLAN), ``approval.decided``, ``mandate.decided``,
  ``speak.revoked`` and ``approval_denied`` (``action.denied{approval.post}``).

A rep turn waits for FastC: it wakes Slow when the first cp generation whose
``fast.request`` ``basis_seq`` is at or after the line's seq ends (``fast.turn``
or ``fast.cancelled``), so a relay from that turn lands in the same step. With
no FastC, or at the close, it wakes at once.

The timer, from the log and constants alone (rule 12, S5b): at each
``slow.step.completed`` whose step made no successful ``finish``, it is due at
that event's ``t_ms`` plus the step's successful ``wait`` (``timer``); in the
call without one, plus ``HEARTBEAT_S`` (``heartbeat``). A wait never delays it
past the heartbeat in the call; outside the call only a wait arms it. Any
``slow.step.started`` disarms it. Nothing else a step does moves it."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from proxyloop.contract.events import Event

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

HEARTBEAT_S = 15  # root decision (S1-SYS-29): under the rep's hold_s of 30 s
REASONS = frozenset(
    {"relay", "rep_turn", "strike", "call_closed", "timer", "heartbeat"}
    | {"fence", "replan", "approval.decided", "mandate.decided", "speak.revoked"}
    | {"approval_denied"}
)


class Wakes:
    def __init__(self, k: Kernel) -> None:
        self._k, self._call, self._armed = k, False, 0
        self._wait: int | None = None  # the running step's successful wait (s)
        self._done = False  # the running step finished the case
        self._lines: list[int] = []  # rep lines no cp generation has seen yet
        self._gens: set[str] = set()  # cp generations that saw one, not ended

    def on_event(self, e: Event) -> None:
        p, cp = e.payload, e.payload.get("lane") == "cp"
        if e.type == "f2s.msg":
            self._wake("relay")
        elif e.type == "chan.opened" and cp:
            self._call = True
        elif e.type == "chan.closed" and cp:
            if self._lines or self._gens:  # FastC will not answer them now
                self._wake("rep_turn")
            self._call, self._lines, self._gens = False, [], set()
            self._wake("call_closed")
        elif e.type == "utt.final" and p["speaker"] == "partner" and self._call:
            if "cp" in self._k.lanes:  # FastC answers it first
                self._lines.append(e.seq)
            else:
                self._wake("rep_turn")
        elif e.type == "fast.request" and cp and self._lines:
            basis = cast(int, p["basis_seq"])
            if self._lines[0] <= basis:
                self._gens.add(str(p["gen_id"]))
                self._lines = [seq for seq in self._lines if seq > basis]
        elif e.type in ("fast.turn", "fast.cancelled") and p["gen_id"] in self._gens:
            self._gens.discard(str(p["gen_id"]))
            self._wake("rep_turn")
        elif e.type == "chan.strike" and self._call:
            self._wake("strike")
        elif e.type == "slow.step.started":
            self._armed += 1
            self._wait, self._done = None, False
        elif e.type == "slow.tool" and p["ok"] and p["name"] in ("wait", "finish"):
            if p["name"] == "wait":
                self._wait = cast(dict[str, int], p["args"])["seconds"]  # SlowTools
            self._done |= p["name"] == "finish"
        elif e.type == "slow.step.completed" and not self._done:
            self._arm(e.t_ms)

    def _wake(self, reason: str) -> None:
        if self._k.slow:
            self._k.slow.wake(reason)

    def _arm(self, t_ms: int) -> None:
        after, why = self._wait, "timer"
        if self._call and (after is None or after > HEARTBEAT_S):
            after, why = HEARTBEAT_S, "heartbeat"
        if after is None or not self._k.slow:
            return
        self._armed += 1
        k, armed, due = self._k, self._armed, t_ms + 1000 * after

        async def fire() -> None:  # unless a step started since
            if (left := due - k.now()) > 0:
                await k.sleep(left / 1000)
            if armed == self._armed:
                self._wake(why)

        k.spawn(fire())
