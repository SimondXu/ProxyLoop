"""Reality: which adapter each role ran with, and the claim rules (§14).

``Manifest.reality``, ``Manifest.models``, ``cfg`` and the ``llm.call``
records must agree. For a claimed role the served model is checked on each
successful ``llm.call``: ``served_model_echo`` (what the endpoint said it
served) must equal ``RoleModel.served_model`` when the manifest names one
(a LoRA slot, a dated hosted id), else the ``ModelRef.model_id`` the call
requested (``requested_model == model_ref.model_id`` is a contract rule).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Sequence

from proxyloop.contract import CONTRACT_VERSION
from proxyloop.contract.bundle import Manifest
from proxyloop.contract.config import SessionConfig
from proxyloop.contract.llm import AdapterKind, LLMCallRecord, LLMRole, ModelRef
from proxyloop.contract.protocol import fingerprint

_REAL = AdapterKind.REAL_HTTP
_NOT_LIVE = (AdapterKind.TEST_FAKE, AdapterKind.RECORDED_REPLAY)


def role_refs(cfg: SessionConfig) -> dict[str, ModelRef]:
    world = cfg.world
    refs = {"fast_user": cfg.fast_user, "fast_cp": cfg.fast_cp, "slow": cfg.slow}
    refs |= {"ear": world.ear, "mouth": world.mouth, "simuser": world.simuser}
    return refs | ({"teacher": cfg.teacher} if cfg.teacher is not None else {})


def label(ref: ModelRef) -> str:
    """vllm | hosted | baseline_fsm | recorded_replay | test_fake."""
    if ref.kind is AdapterKind.REAL_HTTP:
        return "vllm" if ref.endpoint == "vllm" else "hosted"
    return "baseline_fsm" if ref.kind is AdapterKind.BASELINE else ref.kind.value


def reality_report(manifest: Manifest) -> dict[str, str]:
    return {role: label(model.ref) for role, model in manifest.models.items()}


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
        elif c.model_ref != refs.get(c.role):
            out.append(f"call {c.call_id}: model_ref is not the cfg's {c.role} model")
        if c.error is not None and (c.response_sha is not None or c.usage is not None):
            out.append(f"call {c.call_id} failed yet records a response or usage")
    ids = Counter(c.request_id for c in calls if c.request_id)
    if dups := sorted(i for i, n in ids.items() if n > 1):
        out.append(f"request_ids shared by several calls: {dups}")
    return out


def _call_failures(m: Manifest, c: LLMCallRecord) -> list[str]:
    where = f"call {c.call_id} ({c.role})"
    if c.adapter_kind is not AdapterKind.REAL_HTTP:
        return [f"{where} is {c.adapter_kind}, not real_http"]
    if c.error is not None:  # a failed attempt: no response, no usage
        return []
    model = m.models.get(c.role)
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
) -> list[str]:
    out: list[str] = []
    ran = {c.role for c in calls if c.error is None and c.adapter_kind is _REAL}
    for role in sorted(roles):
        if m.reality.get(role) is not _REAL:
            out.append(f"claimed role {role} ran {m.reality.get(role)}")
        if role not in ran:
            out.append(f"claimed role {role} has no successful real_http call")
    for c in calls:
        out += _call_failures(m, c) if c.role in roles else []
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
    return out
