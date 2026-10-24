"""Opt-in, bounded tracing. Export only timing/status and static operation names.

Never export URLs with paths/queries, headers, identities, prompts, image bytes,
exception messages, or stack traces. Sanitization happens before Azure receives
spans, including spans produced by third-party HTTP/Flask instrumentation.
"""

import functools
import logging
import os
import re
from urllib.parse import urlsplit

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import SpanKind, Status

_provider = None
_OPERATIONS = {
    "app.startup",
    "ai.messages",
    "image.derivatives",
    "image.derivatives.png",
    "image.derivatives.resize",
    "image.derivatives.webp",
    "image.process",
}
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


def telemetry_resource(commit, build_id):
    # Explicit slot setting, not a host, identity or arbitrary OTEL attributes.
    # In-place releases keep this slot-local; slot swaps remain unsupported.
    slot = os.getenv("TELEMETRY_SLOT", "").strip().lower()
    slot = slot if slot in {"production", "staging"} else "unknown"
    build = build_id if re.fullmatch(r"[a-zA-Z0-9._-]{1,100}", build_id) else "source"
    return Resource({
        "service.name": "image-library-container" if build_id else "image-library",
        "service.version": commit if re.fullmatch(r"[0-9a-f]{40}", commit) else "unknown",
        "service.instance.id": f"{slot}:{build}",
        "deployment.environment.name": slot,
        "image_library.slot": slot,
    })


def sanitize_span(span):
    """Copy an immutable SDK span into a strictly allowlisted export record."""
    original = span.attributes or {}
    attrs = {}
    method = original.get("http.request.method", original.get("http.method", ""))
    method = method if method in _METHODS else "HTTP"
    route = original.get("http.route", "")
    if route and span.kind == SpanKind.SERVER:
        # Flask supplies the route template, never request.path or filenames.
        attrs["http.route"] = route
    for key in ("http.status_code", "http.response.status_code"):
        value = original.get(key)
        if isinstance(value, int):
            attrs[key] = value
    if "http.method" in original or "http.request.method" in original:
        attrs["http.method"] = method
        attrs["http.request.method"] = method
    raw_url = original.get("url.full", original.get("http.url", ""))
    try:
        host = urlsplit(raw_url).hostname or ""
    except ValueError:
        host = ""
    if host:
        # Host only: Graph identifiers, SAS tokens, stock search terms, etc.
        attrs["http.url"] = f"https://{host}/"
        attrs["server.address"] = host
    if span.name in _OPERATIONS:
        name = span.name
    elif span.kind == SpanKind.SERVER:
        name = f"{method} {route or 'unmatched'}"
    else:
        name = method
    return ReadableSpan(
        name=name, context=span.context, parent=span.parent,
        resource=span.resource, kind=span.kind, attributes=attrs,
        events=(), links=(), status=Status(span.status.status_code),
        start_time=span.start_time, end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class SafeTraceExporter(SpanExporter):
    def __init__(self, delegate):
        self.delegate = delegate

    def export(self, spans):
        return self.delegate.export([sanitize_span(span) for span in spans])

    def shutdown(self):
        self.delegate.shutdown()

    def force_flush(self, timeout_millis=30000):
        return self.delegate.force_flush(timeout_millis)


def initialize_telemetry(app, *, commit="unknown", build_id="") -> bool:
    """Use the existing Insights resource; never enable exporters in local tests."""
    global _provider
    connection = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if not connection or os.getenv("TELEMETRY_ENABLED", "true").lower() == "false":
        return False
    if os.getenv("TEST_MODE", "").lower() in {"1", "true", "yes"}:
        return False
    try:
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
        from opentelemetry.instrumentation.flask import FlaskInstrumentor
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        from opentelemetry.instrumentation.threading import ThreadingInstrumentor

        if _provider is None:
            resource = telemetry_resource(commit, build_id)
            provider = TracerProvider(resource=resource)
            exporter = AzureMonitorTraceExporter(
                connection_string=connection, disable_offline_storage=True,
                tracer_provider=provider,
                timeout=2, read_timeout=5, retry_total=1,
            )
            provider.add_span_processor(BatchSpanProcessor(
                SafeTraceExporter(exporter), max_queue_size=2048,
                max_export_batch_size=256, schedule_delay_millis=5000,
                export_timeout_millis=5000,
            ))
            RequestsInstrumentor().instrument(tracer_provider=provider)
            ThreadingInstrumentor().instrument()
            _provider = provider
        FlaskInstrumentor.instrument_app(app, tracer_provider=_provider)
        return True
    except Exception as exc:
        # Diagnostics must not take the application down or print credentials.
        logging.getLogger(__name__).warning(
            "Application Insights tracing unavailable (%s)", type(exc).__name__,
        )
        return False


def tracer():
    return (_provider.get_tracer(__name__) if _provider else trace.get_tracer(__name__))


def traced(name, *, kind=SpanKind.INTERNAL):
    """Trace fixed operation names only; no arguments, results, or exceptions."""
    if name not in _OPERATIONS:
        raise ValueError("Telemetry operation must be allowlisted")

    def decorate(func):
        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            with tracer().start_as_current_span(
                name, kind=kind, record_exception=False, set_status_on_exception=False,
            ) as span:
                try:
                    return func(*args, **kwargs)
                except Exception:
                    span.set_status(trace.StatusCode.ERROR)
                    raise
        return wrapped
    return decorate
