import pytest
from flask import Flask
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, Status, StatusCode

from src import telemetry


def provider_and_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource({"service.name": "test"}))
    provider.add_span_processor(SimpleSpanProcessor(telemetry.SafeTraceExporter(exporter)))
    return provider, exporter


def test_export_removes_urls_headers_prompts_exception_text_and_events():
    provider, exporter = provider_and_exporter()
    with provider.get_tracer("test").start_as_current_span("unsafe-private-filename", kind=SpanKind.CLIENT) as span:
        span.set_attributes({
            "http.url": "https://user:password@graph.microsoft.com/private/photo.jpg?token=secret",
            "http.method": "GET", "http.status_code": 403,
            "http.request.header.authorization": "Bearer secret",
            "gen_ai.prompt": "private prompt", "enduser.id": "someone@example.org",
        })
        span.record_exception(ValueError("sensitive exception"))
        span.set_status(Status(StatusCode.ERROR, "sensitive status"))
    exported = exporter.get_finished_spans()[0]
    assert exported.name == "GET"
    assert exported.attributes["http.url"] == "https://graph.microsoft.com/"
    assert exported.attributes["http.status_code"] == 403
    assert exported.status.description is None
    assert exported.status.status_code == StatusCode.ERROR
    assert not exported.events
    for value in ("photo.jpg", "secret", "sensitive", "private", "someone@"):
        assert value not in str(exported.attributes)
    provider.shutdown()


def test_flask_spans_use_route_template_not_actual_path_or_query():
    provider, exporter = provider_and_exporter()
    app = Flask(__name__)

    @app.get("/image/<path:filename>")
    def image(filename):
        return "ok"

    FlaskInstrumentor.instrument_app(app, tracer_provider=provider)
    try:
        # Do not preserve test-client context; production tears it down per request.
        response = app.test_client().get("/image/private-photo.jpg?token=secret")
        assert response.status_code == 200
        span = exporter.get_finished_spans()[0]
        assert span.name == "GET /image/<path:filename>"
        assert "private-photo" not in str(span.attributes)
        assert "secret" not in str(span.attributes)
    finally:
        FlaskInstrumentor.uninstrument_app(app)
        provider.shutdown()


def test_custom_operation_preserves_parent_and_exception_without_recording_content(monkeypatch):
    provider, exporter = provider_and_exporter()
    monkeypatch.setattr(telemetry, "_provider", provider)

    @telemetry.traced("image.process")
    def process(value):
        raise ValueError(value)

    with provider.get_tracer("test").start_as_current_span("parent") as parent:
        with pytest.raises(ValueError, match="private"):
            process("private")
    span = exporter.get_finished_spans()[0]
    assert span.name == "image.process"
    assert span.parent.span_id == parent.get_span_context().span_id
    assert span.status.status_code == StatusCode.ERROR
    assert not span.events
    provider.shutdown()


def test_telemetry_is_opt_in_and_disabled_in_test_mode(monkeypatch):
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    assert not telemetry.initialize_telemetry(Flask(__name__))
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "never-export")
    monkeypatch.setenv("TEST_MODE", "true")
    assert not telemetry.initialize_telemetry(Flask(__name__))


def test_invalid_telemetry_configuration_does_not_break_app(monkeypatch, caplog):
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "invalid-secret-string")
    monkeypatch.setenv("TEST_MODE", "false")
    monkeypatch.setenv("TELEMETRY_ENABLED", "true")
    monkeypatch.setattr(telemetry, "_provider", None)
    assert not telemetry.initialize_telemetry(Flask(__name__))
    assert "invalid-secret-string" not in caplog.text
    assert "tracing unavailable" in caplog.text


def test_enabled_configuration_exports_safe_requests_and_is_idempotent(monkeypatch):
    from azure.monitor.opentelemetry import exporter as azure_exporter
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.instrumentation.threading import ThreadingInstrumentor

    sink = InMemorySpanExporter()
    created = []
    real_exporter = azure_exporter.AzureMonitorTraceExporter
    # Exercise the real SDK constructor (which validates/forwards kwargs), but
    # replace transport/export and disable SDK auxiliary network workers.
    monkeypatch.setenv("APPLICATIONINSIGHTS_STATSBEAT_DISABLED_ALL", "true")
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONTROLPLANE_DISABLED", "true")
    monkeypatch.setattr(real_exporter, "export", lambda self, spans: sink.export(spans))

    def factory(**kwargs):
        created.append(kwargs)
        return real_exporter(**kwargs)

    monkeypatch.setattr(azure_exporter, "AzureMonitorTraceExporter", factory)
    monkeypatch.setattr(telemetry, "_provider", None)
    monkeypatch.setenv(
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "InstrumentationKey=00000000-0000-0000-0000-000000000001;IngestionEndpoint=https://example.invalid/",
    )
    monkeypatch.setenv("TEST_MODE", "false")
    monkeypatch.setenv("TELEMETRY_ENABLED", "true")
    app = Flask(__name__)
    app.add_url_rule("/health", view_func=lambda: "ok")
    other = Flask("other")
    try:
        assert telemetry.initialize_telemetry(app, commit="a" * 40)
        assert telemetry.initialize_telemetry(other, commit="a" * 40)
        assert len(created) == 1
        assert app.test_client().get("/health?private=secret").status_code == 200
        telemetry._provider.force_flush()
        assert sink.get_finished_spans()[0].name == "GET /health"
        assert "secret" not in str(sink.get_finished_spans()[0].attributes)
    finally:
        FlaskInstrumentor.uninstrument_app(app)
        FlaskInstrumentor.uninstrument_app(other)
        RequestsInstrumentor().uninstrument()
        ThreadingInstrumentor().uninstrument()
        if telemetry._provider:
            telemetry._provider.shutdown()
