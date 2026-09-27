"""Reality: which adapter each role ran with, and the claim rules (§14).

``Manifest.reality``, ``Manifest.models``, ``cfg`` and the ``llm.call``
records must agree. For a claimed role the served model is checked on each
successful or billed (cancelled, with usage) ``llm.call``:
``served_model_echo`` (what the endpoint said it served) must equal
``RoleModel.served_model`` when the manifest names one (a LoRA slot, a dated
hosted id), else the ``ModelRef.model_id`` the call requested
(``requested_model == model_ref.model_id`` is a contract rule).
E1: a teacher-substituted Fast call keeps its ``fast_*`` role and carries the
teacher's ``ModelRef``; it is the teacher's call only on the lane whose
``teacher_repair_*`` ablation the cfg sets, and is checked as the teacher's.

A claim is scoped to its Fast model (S1-SYS-14): ``claim_scope`` labels it with
the claimed Fast lanes' ``ModelRef``s. P3 ``not_applicable`` passes only for a
hosted Fast, as hosted-Fast evidence that is never a Qwen claim; a Qwen claim
(``about="qwen"``) needs every claimed Fast lane on vLLM and P3 = pass. A trained
slot (C1) needs its ``adapter_shards``: no kernel records them yet (D4).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Sequence
from typing import Literal

from proxyloop.contract import CONTRACT_VERSION
from proxyloop.contract.bundle import Manifest
from proxyloop.contract.config import AblationId, SessionConfig
from proxyloop.contract.llm import AdapterKind, LLMCallRecord, LLMRole, ModelRef
from proxyloop.contract.protocol import fingerprint

_REAL = AdapterKind.REAL_HTTP
_NOT_LIVE = (AdapterKind.TEST_FAKE, AdapterKind.RECORDED_REPLAY)
_FAST: tuple[LLMRole, ...] = ("fast_user", "fast_cp")
TRAINED_MARK = "-pl-"  # in serving.config.TRAINED_PREFIX: a trained LoRA slot (C1)
About = Literal["qwen"]  # what a claim is about; None: its own Fast ModelRef


def role_refs(cfg: SessionConfig) -> dict[str, ModelRef]:
    world = cfg.world
    refs = {"fast_user": cfg.fast_user, "fast_cp": cfg.fast_cp, "slow": cfg.slow}
    refs |= {"ear": world.ear, "mouth": world.mouth, "simuser": world.simuser}
    return refs | ({"teacher": cfg.teacher} if cfg.teacher is not None else {})


def substituted(cfg: SessionConfig, c: LLMCallRecord) -> bool:
    """E1: a ``fast_<lane>`` call the teacher answered under that lane's
    ``teacher_repair_<lane>`` ablation."""
    lane = c.role.removeprefix("fast_") if c.role in ("fast_user", "fast_cp") else ""
    repair = AblationId(f"teacher_repair_{lane}") if lane else None
    return (
        cfg.teacher is not None
        and c.model_ref == cfg.teacher
        and (repair in cfg.ablations)
    )


def _model_role(cfg: SessionConfig, c: LLMCallRecord) -> LLMRole:
    return "teacher" if substituted(cfg, c) else c.role


def label(ref: ModelRef) -> str:
    """vllm | hosted | baseline_fsm | recorded_replay | test_fake."""
    if ref.kind is AdapterKind.REAL_HTTP:
        return "vllm" if ref.endpoint == "vllm" else "hosted"
    return "baseline_fsm" if ref.kind is AdapterKind.BASELINE else ref.kind.value


def reality_report(manifest: Manifest) -> dict[str, str]:
    return {role: label(model.ref) for role, model in manifest.models.items()}


def _fast(m: Manifest, roles: Collection[LLMRole]) -> dict[LLMRole, ModelRef]:
    return {r: m.models[r].ref for r in _FAST if r in roles and r in m.models}


def claim_scope(m: Manifest, roles: Collection[LLMRole]) -> str:
    """What a passing claim is evidence of: the claimed Fast lanes' models."""
    fast = _fast(m, roles)
    if not fast:
        return "no Fast role claimed"
    effort = {r: f" (effort {f.reasoning_effort})" for r, f in fast.items()}
    lanes = ", ".join(
        f"{r}={f.endpoint}:{f.model_id}{effort[r] if f.reasoning_effort else ''}"
        for r, f in fast.items()
    )
    kinds = {label(f) for f in fast.values()}
    if kinds == {"vllm"}:
        return f"Qwen@vllm: {lanes}; P3 {m.p3}"
    if "hosted" in kinds:
        p3 = f"P3 {m.p3}" + (" (hosted Fast)" if m.p3 == "not_applicable" else "")
        return f"hosted-Fast evidence, not a Qwen claim: {lanes}; {p3}"
    return f"{'/'.join(sorted(kinds))}: {lanes}; P3 {m.p3}"


def _scope_failures(
    m: Manifest, roles: Collection[LLMRole], about: About | None
) -> list[str]:
    fast, out = _fast(m, roles), list[str]()
    for role, ref in fast.items():
        slot = m.models[role].served_model or ref.model_id
        trained = ref.endpoint == "vllm" and TRAINED_MARK in slot
        if trained and not m.models[role].adapter_shards:  # D4: the kernel's part
            out.append(f"{role} runs the trained slot {slot} with no adapter_shards")
    if about != "qwen":
        return out
    if not fast:
        return [*out, "a Qwen claim needs a claimed Fast role"]
    for role, ref in fast.items():
        if ref.endpoint != "vllm":
            out.append(f"a Qwen claim needs Qwen@vllm: {role} ran {label(ref)}")
    if m.p3 != "pass":
        out.append(f"a Qwen claim needs P3 pass, not {m.p3}")
    return out


def consistency_failures(m: Manifest, calls: Sequence[LLMCallRecord]) -> list[str]:
    refs = role_refs(m.cfg)
    out: list[str] = []
    if set(m.reality) != set(m.models):
        out.append("manifest reality and models name different roles")
    for role, kind in m.reality.items():
        ref = refs.get(role)
        if ref is None or ref.kind is not kind:
            out.append(f"reality says {role} ran {kind}; cfg says {ref and ref.kind}")
        if role in m.models and m.models[role].ref != ref:
            out.append(f"manifest model for {role} is not the cfg's")
    kinds = [*m.reality.values(), *(c.adapter_kind for c in calls)]
    if m.cfg.live and any(kind in _NOT_LIVE for kind in kinds):
        out.append("a live bundle contains test_fake or recorded_replay")
    for c in calls:
        if c.role not in m.reality:
            out.append(f"call {c.call_id}: role {c.role} is not in the manifest")
        elif c.model_ref != refs.get(_model_role(m.cfg, c)):
            out.append(f"call {c.call_id}: model_ref is not the cfg's {c.role} model")
        if c.error is not None and not c.error.strip():  # chain.py: a success
            out.append(f"call {c.call_id} records an empty error")
        if c.error is None:
            continue
        # A failed call hashes only text delivered, after its first token
        # (check.py resolves the sha; chain.py never lets it back a line), and
        # records usage only when cancelled (billed; S0-SYS-07 item 2).
        if c.response_sha is not None and c.t_first_token is None:
            out.append(f"call {c.call_id} records a response before any token")
        if c.usage is not None and c.error != "cancelled":
            out.append(f"call {c.call_id} failed yet records usage")
    ids = Counter(c.request_id for c in calls if c.request_id)
    if dups := sorted(i for i, n in ids.items() if n > 1):
        out.append(f"request_ids shared by several calls: {dups}")
    return out


def _call_failures(m: Manifest, c: LLMCallRecord) -> list[str]:
    where = f"call {c.call_id} ({c.role})"
    if c.adapter_kind is not AdapterKind.REAL_HTTP:
        return [f"{where} is {c.adapter_kind}, not real_http"]
    billed = c.error == "cancelled" and c.usage is not None  # checked as one
    if c.error is not None and not billed:  # a failed attempt backs no line
        return []
    model = m.models.get(_model_role(m.cfg, c))
    expected = model and (model.served_model or model.ref.model_id)
    out: list[str] = []
    if not c.request_id:
        out.append(f"{where} has no request_id")
    if c.usage is None or min(c.usage.prompt_tokens, c.usage.completion_tokens) <= 0:
        out.append(f"{where} reports zero usage")
    if c.served_model_echo != expected:
        out.append(f"{where} served {c.served_model_echo!r}, configured {expected!r}")
    return out


def claim_failures(
    m: Manifest,
    calls: Sequence[LLMCallRecord],
    roles: Collection[LLMRole],
    profiles: Collection[str],
    about: About | None = None,
) -> list[str]:
    out: list[str] = []
    ok = [c for c in calls if c.error is None and c.adapter_kind is _REAL]
    ran = {_model_role(m.cfg, c) for c in ok}  # a teacher call is the teacher's
    for role in sorted(roles):
        if m.reality.get(role) is not _REAL:
            out.append(f"claimed role {role} ran {m.reality.get(role)}")
        if role not in ran:
            out.append(f"claimed role {role} has no successful real_http call")
    for c in calls:
        out += _call_failures(m, c) if _model_role(m.cfg, c) in roles else []
    if m.contract_version != CONTRACT_VERSION:
        out.append(f"contract {m.contract_version} is not the current one")
    shards = {
        f: sha for model in m.models.values() for f, sha in model.adapter_shards.items()
    }
    if any((m.attestation or {}).get(f) != sha for f, sha in shards.items()):
        out.append("the attestation does not match the adapter card")
    for profile in sorted(set(profiles) | set(m.fingerprints)):
        try:
            current = fingerprint(profile)
        except (KeyError, ValueError):
            current = None
        if m.fingerprints.get(profile) != current:
            out.append(f"fingerprint of {profile} is not the current contract's")
    on_vllm = any(m.models[r].ref.endpoint == "vllm" for r in roles if r in m.models)
    if m.p3 == "fail" or (m.p3 == "not_applicable" and on_vllm):
        out.append(f"P3 is {m.p3}")
    return out + _scope_failures(m, roles, about)
