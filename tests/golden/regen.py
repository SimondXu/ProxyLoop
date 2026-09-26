"""Rewrite the P1/P2 goldens: ``uv run python -m tests.golden.regen``.

Run it only for a contract change (PLAN §0.3). It prints the per-profile P2 id
digests that go into ``profiles/*.py`` (``p2_ids_sha256``).
"""

from __future__ import annotations

import json

from tests.golden.cases import CASES, GOLDEN
from tests.golden.tokenizer import REPO, REVISION, encode, load_tokenizer

from proxyloop.contract.base import canonical_json, sha256_text
from proxyloop.contract.protocol import (
    EMPTY_THINK,
    PROFILES,
    render_messages,
    render_prompt,
)


def p2_digest(ids: dict[str, list[int]]) -> str:
    return sha256_text(canonical_json(ids))


def main() -> None:
    views = GOLDEN / "views"
    views.mkdir(exist_ok=True)
    ids: dict[str, list[int]] = {}
    for case in CASES:
        view = case.view()
        messages = [
            m.model_dump(include={"role", "content"})
            for m in render_messages(view, case.profile)
        ]
        body = {
            "profile": case.profile,
            "view": view.model_dump(mode="json"),
            "messages": messages,
        }
        (views / f"{case.name}.json").write_text(
            json.dumps(body, indent=1, ensure_ascii=False) + "\n", "utf-8"
        )
        ids[case.name] = encode(render_prompt(view, case.profile, load_tokenizer()))
    by_profile = {
        name: p2_digest({c.name: ids[c.name] for c in CASES if c.profile == name})
        for name in PROFILES
    }
    worst = max(ids, key=lambda name: len(ids[name]))
    p2 = {
        "tokenizer": {"repo": REPO, "revision": REVISION},
        "chat_template_kwargs": {
            "add_generation_prompt": True,
            "enable_thinking": False,
        },
        "empty_think": {
            "text": EMPTY_THINK,
            "hex": EMPTY_THINK.encode("utf-8").hex(),
            "ids": encode(EMPTY_THINK),
        },
        "worst_case": {"case": worst, "tokens": len(ids[worst])},
        "profiles": by_profile,
        "cases": {name: " ".join(map(str, row)) for name, row in ids.items()},
    }
    (GOLDEN / "p2_ids.json").write_text(json.dumps(p2, indent=1) + "\n", "utf-8")
    for name, digest in by_profile.items():
        print(f"{name}: p2_ids_sha256={digest}")


if __name__ == "__main__":
    main()
