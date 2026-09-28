"""A synthetic success-path run for ``obs.progress`` and ``obs.watch``: one
builder method per fixed-emitter step, each returning the event id (or the
utt id) the next step cites, so a table-driven test can drop one step and see
which milestone or watch item it moves."""

from __future__ import annotations

from tests.obs.bundles import Log

from proxyloop.obs import detectors

P = dict[str, object]


class Run:
    def __init__(self, run_id: str = "rP", task_ref: str = "fam-a@1") -> None:
        self.log = Log(run_id)
        self.log.events[0].payload["task_ref"] = task_ref
        self.start, self._utt = self.log.start, 0

    def inputs(self) -> detectors.Inputs:
        return detectors.Inputs(self.log.events, None, lambda _: None)

    def seq(self, event_id: str) -> int:
        return next(e.seq for e in self.log.events if e.event_id == event_id)

    # The world: the rep's policy, its mouth and its ear.
    def policy(
        self,
        frm: str,
        to: str,
        kind: str,
        ref: str | None = None,
        rung: int | None = None,
        cause: str | None = None,
        reason: str | None = None,
    ) -> str:
        intent: P = {"kind": kind, "offer_ref": ref, "say": [], "ask": []}
        if kind in ("offer", "final_offer"):
            intent["say"] = [["monthly_price", "60.00"], ["term_months", "12"]]
        if reason is not None:
            intent["reason"] = reason
        payload: P = {"from": frm, "to": to, "intent": intent, "rung": rung}
        causes = () if cause is None else (cause,)
        return self.log.add("rep.policy", "world.policy", "world", payload, causes)

    def ear(self, act: str, utt_id: str = "u") -> str:
        ear: P = {"utt_id": utt_id, "act": act, "args": {}, "call_id": "e"}
        return self.log.add("rep.ear", "world.ear", "world", ear, (self.start,))

    def say(self, policy: str) -> str:
        """The rep voices ``policy``: rep.mouth -> utt.final; its utt id."""
        mouth: P = {"intent": {}, "text": "PRIV", "fidelity_ok": True, "attempts": 1}
        said = self.log.add("rep.mouth", "world.mouth", "world", mouth, (policy,))
        self._utt += 1
        utt = f"cp-{self._utt}"
        line: P = {"lane": "cp", "speaker": "partner", "utt_id": utt, "text": "PRIV"}
        self.log.add("utt.final", "kernel", "agent", line, (said,))
        return utt

    def identify(self) -> str:
        return self.policy("IDENTIFY", "DISCOVER", "how_can_help", cause=self.start)

    def offer(self, lever: str, rung: int, ref: str, frm: str = "DISCOVER") -> str:
        """The rep hears ``lever`` and offers rung ``rung`` (world ``ref``);
        the utt id of the line that says it."""
        ear = self.ear(lever, f"lever-{len(self.log.events)}")
        kind = "offer"
        return self.say(self.policy(frm, "OFFER", kind, ref, rung, cause=ear))

    # The agent: GUIDEs, records, read-backs, approvals, the accept.
    def guide(self, move: str, *slots: str) -> str:
        guide: P = {"move": move, "slots": list(slots)}
        msg: P = {"msg_id": f"s2f-{len(self.log.events)}", "lane": "cp"}
        msg |= {"type": "GUIDE", "guide": guide, "approval_id": None}
        return self.log.add("s2f.msg", "guard", "agent", msg, (self.start,))

    def record(
        self, utt: str, ref: str = "offer-1", rev: int = 1, th: str = "th"
    ) -> str:
        slots = [{"field": "monthly_price", "value": "6000", "status": "unknown",
                  "source_utt": utt}]  # fmt: skip
        offer: P = {"offer_ref": ref, "revision": rev, "slots": slots}
        offer["terms_hash"] = th
        return self.log.add("offer.recorded", "guard", "agent", offer, (self.start,))

    def confirmed(self, ref: str = "offer-1", rev: int = 1, th: str = "th") -> str:
        up: P = {"offer_ref": ref, "revision": rev, "terms_hash": th}
        up["slot_statuses"] = {"monthly_price": "confirmed"}
        return self.log.add("readback.updated", "guard", "agent", up, (self.start,))

    def request(self, ref: str = "offer-1", rev: int = 1, th: str = "th") -> str:
        binding: P = {"offer_ref": ref, "revision": rev, "account_ref": "acct"}
        binding |= {"principal_ref": "me", "purpose": "accept", "authority_epoch": 0}
        card: P = {"approval_id": "a1", "offer_ref": ref, "revision": rev,
                   "terms_hash": th, "readback_text": "PRIV", "authority_epoch": 0,
                   "expires_ms": 10**9, "binding": binding}  # fmt: skip
        return self.log.add("approval.requested", "guard", "agent", card, (self.start,))

    def post(self, card: str, decision: str = "granted", by: str = "ui") -> str:
        post: P = {"subject": "approval", "subject_id": "a1", "decision": decision}
        post |= {"subject_hash": "th", "authority_epoch": 0}
        causes = (card,) if by == "sim_approver" else ()
        return self.log.add("approval.post", by, "agent", post, causes)

    def decide(self, card: str, decision: str = "granted", by: str = "ui") -> str:
        sent = self.post(card, decision, by)
        decided: P = {"approval_id": "a1", "decision": decision, "by": by}
        return self.log.add("approval.decided", "kernel", "agent", decided, (sent,))

    def authorize(self, grant: str, th: str = "th") -> str:
        cap: P = {"cap_id": "cap-1", "business_action_id": "b", "terms_hash": th}
        cap |= {"intent": "accept_offer", "epoch": 0, "expires_ms": 10**9}
        auth: P = {"intent": "accept_offer", "capability": cap}
        return self.log.add("action.authorized", "guard", "agent", auth, (grant,))

    def verbatim(self, auth: str) -> str:
        line: P = {"lane": "cp", "kind": "accept", "text": "PRIV", "cap_id": "cap-1"}
        return self.log.add("speak.verbatim", "guard", "agent", line, (auth,))

    def release(self, said: str) -> str:
        """speak.released -> the cp utt.delivered; the accept line's utt id."""
        rel = self.log.add("speak.released", "kernel", "agent", {"lane": "cp"},
                           (said,))  # fmt: skip
        utt = f"accept-{len(self.log.events)}"
        out: P = {"lane": "cp", "utt_id": utt, "text_generated": "PRIV"}
        out |= {"text_heard": "PRIV", "interrupted": False}
        self.log.add("utt.delivered", "kernel", "agent", out, (rel,))
        return utt

    def revoke(self, said: str, reason: str = "fence") -> str:
        out: P = {"lane": "cp", "reason": reason, "cap_id": "cap-1"}
        return self.log.add("speak.revoked", "kernel", "agent", out, (said,))

    def commit(self, utt: str, ref: str = "save-1", frm: str = "OFFER") -> str:
        ear = self.ear("accept", utt)
        intent: P = {"kind": "confirmed", "offer_ref": ref, "say": [], "ask": []}
        policy: P = {"from": frm, "to": "CONFIRMED", "rung": 0, "intent": intent}
        pid = self.log.add("rep.policy", "world.policy", "world", policy, (ear,))
        heard: P = {"utt_id": utt, "offer_ref": ref}
        return self.log.add("rep.commit_heard", "world.policy", "world", heard,
                            (ear, pid))  # fmt: skip

    def verified(self, verdict: str = "ok", outcome: str = "completed") -> str:
        """Slow's finish(``outcome``) and the verifier's completion.decided."""
        args: P = {"outcome": outcome}
        done: P = {"name": "finish", "args": args, "result_text": "v", "ok": True}
        tool = self.log.add("slow.tool", "slow", "agent", done | {"code": None},
                            (self.start,))  # fmt: skip
        decided: P = {"verdict": verdict, "reasons": []}
        return self.log.add("completion.decided", "guard", "agent", decided, (tool,))

    def status(self, status: str) -> str:
        changed: P = {"previous": "IN_CALL", "status": status}
        return self.log.add("status.changed", "guard", "agent", changed, (self.start,))

    def tool(self, name: str, ok: bool, code: str | None, text: str = "PRIV") -> str:
        done: P = {"name": name, "args": {}, "result_text": text, "ok": ok}
        done["code"] = code
        return self.log.add("slow.tool", "slow", "agent", done, (self.start,))

    def end(self, reason: str = "done") -> None:
        self.log.end(reason)


def success(skip: frozenset[str] = frozenset(), rung: int = 1) -> Run:
    """The generic success path, ``skip`` naming steps to leave out:
    ask_discount, record, lever_guide, lever_ear, later_rung,
    readback, request, decide, release, commit, verified. ``rung`` 0 accepts
    the first rung's offer (no lever after it), 1 the second's."""
    r = Run()
    r.identify()
    if "ask_discount" not in skip:
        r.guide("ask_discount")
    utt = r.offer("ask_discount", 0, "save-1")
    ref = "offer-1"
    if "record" not in skip:
        r.record(utt, "offer-1", th="th0" if rung else "th")
    if rung:
        if "lever_guide" not in skip:
            r.guide("mention_tenure")
        lever = "clarify" if "lever_ear" in skip else "tenure"
        ear = r.ear(lever, f"lever-{len(r.log.events)}")
        if "later_rung" not in skip:
            utt = r.say(r.policy("OFFER", "FINAL", "final_offer", "save-2", 1, ear))
        if "record" not in skip:
            r.record(utt, "offer-2")
        ref = "offer-2"
    r.guide("ask_readback", f"offer:{ref}.monthly_price")
    if "readback" not in skip:
        r.confirmed(ref)
    grant = r.start
    if "request" not in skip:
        card = r.request(ref)
        grant = card if "decide" in skip else r.decide(card)
    said = r.verbatim(r.authorize(grant))
    accept = r.release(said) if "release" not in skip else "never-said"
    if "commit" not in skip:
        r.commit(accept, "save-2" if rung else "save-1")
    if "verified" not in skip:
        r.verified()
        r.status("VERIFIED_COMPLETE")
    r.end("done")
    return r
