import os
import time                                        # 👈 NEW: High-precision timer for TTFT
from groq import AsyncGroq
from opentelemetry import trace                    # 👈 NEW: OpenTelemetry tracing API
from app.services.metrics import llm_token_spend_total
from app.services.prompt_registry import get_registry
from app.connectors.registry import connector_registry
from dotenv import load_dotenv

load_dotenv()

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
tracer = trace.get_tracer(__name__)                # 👈 NEW: Grab tracer instance


async def stream_llm_tokens(
    prompt: str,
    version: str = None,
    tenant_id: str = None,
    slack_thread: str = None,
    jira_ticket: str = None,
    model: str = "openai/gpt-oss-120b",
    **kwargs
):
    if tenant_id:
        print(f"🧠 LLM processing request for tenant: {tenant_id}")

    registry = get_registry()

    if not version:
        version = await registry.get_active_version()

    prompt_config = registry.get_prompt(version)

    if prompt_config:
        system_prompt = prompt_config.get("template", "You are a concise, helpful support agent.")
    else:
        system_prompt = "You are a concise, helpful support agent."

    context_blocks = []

    # Intercept Slack Request
    if slack_thread:
        print(f"🔗 Intercepting request for Slack context: {slack_thread}")
        slack_connector = connector_registry.get_connector("slack")
        if slack_connector:
            try:
                slack_context = await slack_connector.fetch(slack_thread)
                context_blocks.append(f"--- SLACK CONTEXT ---\n{slack_context}\n---------------------")
            except Exception as e:
                print(f"⚠️ Slack API Error: {e}")
                context_blocks.append(f"--- SLACK CONTEXT ---\n[Failed to retrieve Slack thread: {e}]\n---------------------")

    # Intercept Jira Request
    if jira_ticket:
        print(f"🔗 Intercepting request for Jira context: {jira_ticket}")
        jira_connector = connector_registry.get_connector("jira")
        if jira_connector:
            try:
                jira_context = await jira_connector.fetch(jira_ticket)
                context_blocks.append(f"--- JIRA CONTEXT ---\n{jira_context}\n--------------------")
            except Exception as e:
                print(f"⚠️ Jira API Error: {e}")
                context_blocks.append(f"--- JIRA CONTEXT ---\n[Failed to retrieve Jira ticket: {e}]\n--------------------")

    if context_blocks:
        injected_context = "\n\n".join(context_blocks)
        system_prompt = f"System Context Updates:\n{injected_context}\n\n{system_prompt}"

    # 👇 NEW: Custom OpenTelemetry span wrapping the LLM call + streaming loop
    with tracer.start_as_current_span("llm.stream_tokens") as span:
        span.set_attribute("llm.model", model)
        span.set_attribute("llm.prompt_version", str(version))
        span.set_attribute("tenant.id", str(tenant_id))

        start_time = time.perf_counter()
        first_token_seen = False

        stream = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            model=model,
            stream=True,
        )

        token_count = 0
        try:
            async for chunk in stream:
                token_text = chunk.choices[0].delta.content
                if token_text:
                    # 👇 NEW: Record TTFT on the very first token
                    if not first_token_seen:
                        ttft_ms = (time.perf_counter() - start_time) * 1000
                        span.set_attribute("llm.ttft_ms", round(ttft_ms, 2))
                        span.add_event("first_token_received")
                        first_token_seen = True

                    token_count += 1
                    yield f"data: {token_text}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            # 👇 NEW: Stamp final token count and total stream duration
            total_ms = (time.perf_counter() - start_time) * 1000
            span.set_attribute("llm.token_count", token_count)
            span.set_attribute("llm.total_duration_ms", round(total_ms, 2))

            if token_count > 0:
                llm_token_spend_total.labels(
                    prompt_version=version, tenant_id=str(tenant_id)
                ).inc(token_count)