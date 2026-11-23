# app/core/telemetry.py
from dotenv import load_dotenv; load_dotenv()
import os
from prometheus_client import Histogram, Counter
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

# --- Prometheus Metrics (Existing) ---
GATEWAY_LATENCY = Histogram(
    "gateway_request_latency_seconds",
    "Gateway request latency in seconds",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

CACHE_HITS = Counter("gateway_cache_hits_total", "Total Redis cache hits")
CACHE_MISSES = Counter("gateway_cache_misses_total", "Total Redis cache misses")
LLM_COST_USD = Counter("gateway_llm_cost_usd", "Total cost of LLM API calls in USD")


# --- OpenTelemetry Distributed Tracing (New) ---
def setup_telemetry(app):
    """Initialize OpenTelemetry tracing and auto-instrument FastAPI, Redis, and HTTPX."""
    resource = Resource.create({
        SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "streaming-ai-gateway"),
        "deployment.environment": os.getenv("ENV", "local"),
    })

    provider = TracerProvider(resource=resource)
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")

    if otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        print(f"📡 OpenTelemetry exporting via OTLP -> {otlp_endpoint}")
    else:
        exporter = ConsoleSpanExporter()
        print("📡 OpenTelemetry active (Console exporter — set OTEL_EXPORTER_OTLP_ENDPOINT for Tempo/Jaeger)")

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    RedisInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()

    return trace.get_tracer(__name__)