import os
from groq import AsyncGroq
from app.services.metrics import llm_token_spend_total
from app.services.prompt_registry import get_registry
from app.connectors.registry import connector_registry

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

async def stream_llm_tokens(
    prompt: str, 
    version: str = None, 
    tenant_id: str = None,
    slack_thread: str = None, # 👇 NEW
    jira_ticket: str = None   # 👇 NEW
):
    if tenant_id:
        print(f"🧠 LLM processing request for tenant: {tenant_id}")
        
    # 0. Get the registry lazily inside the function
    registry = get_registry()
    
    # 1. If no specific version is requested, get the active one from Redis
    if not version:
        version = await registry.get_active_version()
        
    # 2. Fetch the prompt configuration from our YAML registry
    prompt_config = registry.get_prompt(version)
    
    # 3. Apply the YAML config, or fallback to defaults
    if prompt_config:
        system_prompt = prompt_config.get("template", "You are a concise, helpful support agent.")
        model = prompt_config.get("model", "llama-3.1-8b-instant")
    else:
        system_prompt = "You are a concise, helpful support agent."
        model = "llama-3.1-8b-instant"

    # 👇 4. NEW: Fetch and Inject Enterprise Context
    context_blocks = []

    # Intercept Slack Request
    if slack_thread:
        print(f"🔗 Intercepting request for Slack context: {slack_thread}")
        slack_connector = connector_registry.get_connector("slack")
        if slack_connector:
            try:
                # 👇 NEW: Wrapped in a try/except block to catch API errors!
                slack_context = await slack_connector.fetch(slack_thread)
                context_blocks.append(f"--- SLACK CONTEXT ---\n{slack_context}\n---------------------")
            except Exception as e:
                print(f"⚠️ Slack API Error: {e}")
                # Tell the LLM that the Slack fetch failed gracefully!
                context_blocks.append(f"--- SLACK CONTEXT ---\n[Failed to retrieve Slack thread: {e}]\n---------------------")

    # (We will add Jira interception here in the next step!)
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
                # Tell the LLM that the Jira fetch failed gracefully!
                context_blocks.append(f"--- JIRA CONTEXT ---\n[Failed to retrieve Jira ticket: {e}]\n--------------------")

    # If we have any context, inject it at the very top of the system prompt
    if context_blocks:
        injected_context = "\n\n".join(context_blocks)
        system_prompt = f"System Context Updates:\n{injected_context}\n\n{system_prompt}"

    # 5. Call the LLM
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
                token_count += 1
                yield f"data: {token_text}\n\n"
        yield "data: [DONE]\n\n"
    finally:
        if token_count > 0:
            # Ensure tenant_id is cast to a string just in case it's None, to avoid Prometheus errors
            llm_token_spend_total.labels(prompt_version=version, tenant_id=str(tenant_id)).inc(token_count)