"""``SpanRecord`` → OTel ``ReadableSpan`` → OTLP/HTTP (ADR-0008).

The only module that imports OpenTelemetry; ``obs.trace`` loads it lazily, on
the export path only. Spans keep the mapping's ids and times. A failed export
raises: nothing is dropped silently, and the only retries are the SDK's own.
"""

from __future__ import annotations

from collections.abc import Sequence

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.util.instrumentation import InstrumentationScope
from opentelemetry.trace import Link, SpanContext, Status, StatusCode, TraceFlags

from proxyloop.obs.trace import SpanRecord

_SCOPE = InstrumentationScope("proxyloop.obs.trace")


class ExportFailed(Exception):
    """The collector did not take the spans."""


def exporter(endpoint: str, timeout_s: float = 10.0) -> SpanExporter:
    return OTLPSpanExporter(endpoint=endpoint, timeout=timeout_s)


def readable(records: Sequence[SpanRecord]) -> list[ReadableSpan]:
    resources: dict[str, Resource] = {}
    spans: list[ReadableSpan] = []
    for r in records:
        resource = resources.setdefault(
            r.service, Resource({"service.name": r.service})
        )
        spans.append(
            ReadableSpan(
                name=r.name,
                context=_context(r.trace_id, r.span_id),
                parent=_context(r.trace_id, r.parent_id) if r.parent_id else None,
                resource=resource,
                attributes=dict(r.attributes),
                links=[Link(_context(r.trace_id, s)) for s in r.links],
                status=Status(StatusCode[r.status]),
                start_time=r.start_ns,
                end_time=r.end_ns,
                instrumentation_scope=_SCOPE,
            )
        )
    return spans


def export(records: Sequence[SpanRecord], sink: SpanExporter) -> None:
    if sink.export(readable(records)) is not SpanExportResult.SUCCESS:
        raise ExportFailed(f"{len(records)} spans were not exported")


def _context(trace_id: str, span_id: str) -> SpanContext:
    return SpanContext(
        int(trace_id, 16), int(span_id, 16), True, TraceFlags(TraceFlags.SAMPLED)
    )
