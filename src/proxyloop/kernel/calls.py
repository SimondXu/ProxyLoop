"""The cp call's gate (ADR-0012). ``Kernel._open`` opens the user lane only, and
the case stays INTAKE; ``Calls`` opens the cp lane once, on the first of:
- ``ready``: a public ``fact.recorded`` leaves no readiness key missing. It is
  spawned, so it runs after the Slow act that recorded the fact, never inside;
- ``slow_start``: Slow's ``start_call()``, which Guard allowed only once every
  missing key was asked and the user replied (``guard.needs``), also spawned;
- ``intake_deadline``: ``INTAKE_S`` after the session opened.
A session without Slow or without a user lane has no intake and opens at once
(``no_intake``), as does one whose task needs nothing public (``ready``).

Opening is ``chan.opened{lane: cp, call, reason, missing, ready}`` (untyped
payload keys), the ``call_opened`` status edge, the disclosure, the cp ingress
and then FastC. The rep's clock starts only once the disclosure was said
(``watchdog``), so intake time never becomes a rep strike (R2). ``Calls`` also
holds the needs ledger, folded from every event, for Slow's status bar."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from proxyloop.contract.events import Event
from proxyloop.guard import needs, readiness
from proxyloop.guard.status import status_change
from proxyloop.kernel.channels import Channel

if TYPE_CHECKING:
    from proxyloop.kernel.session import Kernel

# Guard-authored and fixed (I11, C14): the first thing the rep hears.
DISCLOSURE = "Hello, this is an AI assistant calling on behalf of the account holder."
INTAKE_S = 120  # root decision (ADR-0012); the human-demo value: S1-SYS-05
Ingress = Callable[[str, Channel, str], Coroutine[Any, Any, None]]


class Calls:
    def __init__(self, k: Kernel, ingress: Ingress) -> None:
        self._k, self._ingress = k, ingress
        self.required = readiness.required(k.task)
        self.intake = k.slow is not None and "user" in k.channels
        self.needs = needs.Ledger()
        self.opened: Event | None = None  # the chan.opened{cp}
        self.count = 0  # calls opened (ADR-0014 adds a second)
        self.deadline_ms: int | None = None  # while the intake runs
        self.disclosed = asyncio.Event()  # the rep has heard the disclosure

    def missing(self) -> tuple[str, ...]:
        return readiness.missing(self._k.bb, self.required)

    def start(self, root: str) -> None:
        """At ``_open``: the call now, or the intake and its deadline."""
        if not self.intake or not self.missing():
            self._call(root, "ready" if self.intake else "no_intake")
            return
        self.deadline_ms = self._k.now() + 1000 * INTAKE_S
        self._k.spawn(self._deadline(root, self.deadline_ms))

    def on_event(self, e: Event) -> None:
        self.needs = needs.step(self.needs, e)
        if self.opened is not None or self.deadline_ms is None:
            return
        p = e.payload
        if e.type == "fact.recorded" and p["scope"] == "public" and not self.missing():
            self._k.spawn(self._soon(e.event_id, "ready"))
        elif e.type == "slow.tool" and p["name"] == "start_call" and p["ok"]:
            self._k.spawn(self._soon(e.event_id, "slow_start"))

    async def _soon(self, cause: str, reason: str) -> None:  # after the act
        self._call(cause, reason)

    async def _deadline(self, root: str, due: int) -> None:
        if (left := due - self._k.now()) > 0:
            await self._k.sleep(left / 1000)
        self._call(root, "intake_deadline")

    def _call(self, cause: str, reason: str) -> None:
        if self.opened is not None:  # the first condition wins: one call
            return
        k, missing = self._k, self.missing()
        self.count += 1
        said = {"lane": "cp", "call": self.count, "reason": reason}
        said |= {"missing": list(missing), "ready": not missing}
        self.opened = opened = k.emit("chan.opened", "kernel", said, [cause])
        self.deadline_ms = None
        if (status := status_change(k.bb, "call_opened")) is not None:
            k.emit("status.changed", "guard", status, [opened.event_id])
        k.spawn(self._disclose(opened.event_id))
        for key, channel in k.channels.items():
            if key != "user":
                k.spawn(self._ingress(key, channel, opened.event_id))

    async def _disclose(self, opened: str) -> None:  # first cp agent line (I11)
        k = self._k
        line = {"lane": "cp", "kind": "disclosure", "text": DISCLOSURE}
        said = k.emit("speak.verbatim", "guard", line, [opened]).event_id
        released = k.emit("speak.released", "kernel", {"lane": "cp"}, [said])
        heard = [("disclosure", DISCLOSURE, released.event_id)]
        await k.speakers["cp"].speak(heard, interruptible=False)
        self.disclosed.set()
        if "cp" in k.lanes:
            k.spawn(k.lanes["cp"].run())
