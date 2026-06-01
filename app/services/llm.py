import os
from groq import AsyncGroq
from app.services.metrics import llm_token_spend_total
from app.services.prompt_registry import get_registry # <-- Import the getter

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

async def stream_llm_tokens(prompt: str, version: str = None, tenant_id: str = None):
   
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
        system_prompt = prompt_config.get("template")
        model = prompt_config.get("model", "llama-3.1-8b-instant")
    else:
        system_prompt = "You are a concise, helpful support agent."
        model = "llama-3.1-8b-instant"

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
            llm_token_spend_total.labels(prompt_version=version, tenant_id=tenant_id).inc(token_count)