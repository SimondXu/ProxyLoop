"""The OTLP adapter keeps the mapping's ids, parents, links, services, times,
attributes and status, and a dead collector fails loudly."""

from __future__ import annotations

from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode
from tests.obs.test_trace import collect, private_bundle

from proxyloop.obs import otlp


def test_readable_spans_match_the_records(tmp_path: Path) -> None:
    records = collect(private_bundle(tmp_path / "rP"), content=True)
    memory = InMemorySpanExporter()
    otlp.export(records, memory)
    spans = memory.get_finished_spans()
    assert len(spans) == len(records)
    for r, s in zip(records, spans, strict=True):
        assert s.context is not None
        assert (f"{s.context.trace_id:032x}", f"{s.context.span_id:016x}") == (
            r.trace_id,
            r.span_id,
        )
        parent = s.parent and f"{s.parent.span_id:016x}"
        assert parent == r.parent_id
        assert tuple(f"{link.context.span_id:016x}" for link in s.links) == r.links
        assert s.resource.attributes["service.name"] == r.service
        assert (s.name, s.start_time, s.end_time) == (r.name, r.start_ns, r.end_ns)
        assert dict(s.attributes or {}) == dict(r.attributes)
        assert s.status.status_code is StatusCode[r.status]


def test_a_dead_collector_fails_loudly(tmp_path: Path) -> None:
    records = collect(private_bundle(tmp_path / "rP"))
    dead = otlp.exporter("http://127.0.0.1:9/v1/traces", timeout_s=1.0)
    with pytest.raises(otlp.ExportFailed):
        otlp.export(records, dead)
