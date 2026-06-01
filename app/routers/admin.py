from app.services.metrics import hallucination_score
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import json
from app.services.prompt_registry import get_registry, redis_client # Reuse the redis client
registry = get_registry()

router = APIRouter(tags=["Admin"])

class ActivateRequest(BaseModel):
    version: str

# 👇 New Request Model for Canary Setup
class CanaryRequest(BaseModel):
    version: str
    weight: float = Field(..., ge=0.0, le=1.0) # Weight must be between 0.0 and 1.0 (e.g., 0.10 for 10%)

@router.get("/admin/prompts")
async def list_prompts():
    active_version = await registry.get_active_version()
    # Check if there is an active canary in Redis
    canary_raw = await redis_client.get("prompt:canary")
    canary_config = json.loads(canary_raw.decode("utf-8")) if canary_raw else None
    
    return {
        "active_version": active_version,
        "canary_deployment": canary_config,
        "available_prompts": list(registry.registry.keys()),
        "prompts_data": registry.registry
    }

@router.post("/admin/prompts/activate")
async def activate_prompt(req: ActivateRequest):
    try:
        await registry.set_active_version(req.version)
        return {"status": "success", "active_version": req.version}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

# 👇 New Endpoint: Set Canary Version + Weight
@router.post("/admin/canary")
async def set_canary(req: CanaryRequest):
    if req.version not in registry.registry:
        raise HTTPException(status_code=404, detail=f"Prompt version {req.version} not found.")
    
    canary_data = {"version": req.version, "weight": req.weight}
    await redis_client.set("prompt:canary", json.dumps(canary_data))
    return {"status": "canary_set", "config": canary_data}

# 👇 New Endpoint: Cancel Canary Deployment
@router.delete("/admin/canary")
async def delete_canary():
    await redis_client.delete("prompt:canary")
    return {"status": "canary_deleted"}

# 2. Add this class near your other BaseModels
class EvalScore(BaseModel):
    version: str
    score: float

# 3. Add this new endpoint at the bottom of the file
@router.post("/admin/eval")
async def save_evaluation_score(req: EvalScore):
    """Allows the external Eval script to save the RAGAS score to Prometheus."""
    # We use .set() instead of .inc() because this is a Gauge (0.0 to 1.0)
    hallucination_score.labels(prompt_version=req.version, tenant_id="default").set(req.score)
    return {"status": "score_recorded", "version": req.version, "score": req.score}