"""S1-SYS-16 B: ``session.ended`` carries the ledger totals, so an all-unpriced
run no longer reads as zero spend (I10). The manifest's ``Spend`` stays priced
only until S1-CON-03."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import cast

import pytest
from tests.contract.samples import SONNET
from tests.kernel.test_session import SCRIPTS, UNTIL
from tests.support.sessions import fake_config, only_bundle, run

from proxyloop.contract.config import SessionConfig
from proxyloop.contract.llm import AdapterKind

# A test_fake at the relay's rated model id: its fake usage is priced.
PRICED_SLOW = SONNET.model_copy(update={"kind": AdapterKind.TEST_FAKE})


@pytest.mark.parametrize(
    "cfg",
    [
        fake_config(),  # every call unpriced
        fake_config().model_copy(update={"slow": PRICED_SLOW}),
    ],
    ids=["all_unpriced", "slow_priced"],
)
def test_session_ended_totals_match_the_spend_charged_events(
    tmp_path: Path, cfg: SessionConfig
) -> None:
    run(tmp_path, SCRIPTS, until=UNTIL, cfg=cfg)
    events = only_bundle(tmp_path).events
    charged = [e.payload for e in events if e.type == "spend.charged"]
    unpriced = [c for c in charged if c["basis"] == "unpriced"]
    priced = [c for c in charged if c["basis"] == "tokens"]
    assert unpriced  # not vacuous
    spend = cast(dict[str, object], events[-1].payload["spend"])
    assert spend["unpriced_calls"] == len(unpriced)
    assert spend["unpriced_by_role"] == dict(Counter(c["role"] for c in unpriced))
    assert spend["priced_micro_usd"] == sum(cast(int, c["micro_usd"]) for c in priced)
    assert spend["gpu_time_calls"] == 0
    assert cast(int, spend["tokens"]) > 0
    if cfg.slow.model_id == SONNET.model_id:
        assert priced and spend["priced_by_role"] == {"slow": spend["priced_micro_usd"]}
    else:
        assert not priced and spend["priced_by_role"] == {}
