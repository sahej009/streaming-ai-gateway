import os
import yaml
import json
import random
from typing import Dict, Optional
from redis import asyncio as aioredis
from app.services.cache import redis_client


PROMPTS_PATH = "/prompts"

class PromptRegistry:
    async def resolve_version(self, requested_version: str = None) -> str:
        """
        Determines which prompt version to use based on client request, 
        active version in Redis, and Canary A/B routing rules.
        """
        # 1. If the client explicitly asked for a specific version, honor it
        if requested_version:
            return requested_version

        # 2. Get the active version from Redis (fallback to "v1" if not set)
        active_bytes = await redis_client.get("prompt:active_version")
        active_version = active_bytes.decode('utf-8') if active_bytes else "v1"

        # 3. Check if there is an active Canary deployment
        canary_bytes = await redis_client.get("prompt:canary")
        if canary_bytes:
            canary_config = json.loads(canary_bytes)
            canary_version = canary_config.get("version")
            canary_weight = float(canary_config.get("weight", 0.0))

            # Roll the dice for A/B testing!
            if random.random() < canary_weight:
                print(f"🎲 Canary Route Triggered: Sending traffic to {canary_version}")
                return canary_version

        return active_version
    
    def __init__(self, prompts_dir: str = PROMPTS_PATH):
        self.prompts_dir = prompts_dir
        self.registry: Dict[str, dict] = {}
        self.load_prompts()

    def load_prompts(self):
        """Loads all YAML files from the prompts directory into memory."""
        print(f"🔍 Debug: Starting load from {self.prompts_dir}")
        
        if not os.path.exists(self.prompts_dir):
            print(f"❌ Debug: Directory does not exist: {self.prompts_dir}")
            return
            
        files = os.listdir(self.prompts_dir)
        
        for filename in files:
            if filename.endswith((".yaml", ".yml")):
                filepath = os.path.join(self.prompts_dir, filename)
                try:
                    with open(filepath, 'r') as f:
                        data = yaml.safe_load(f)
                        if data and isinstance(data, dict) and "version" in data:
                            self.registry[data["version"]] = data
                            print(f"✅ Debug: Added version {data['version']} to registry")
                        else:
                            print(f"❌ Debug: Skipped {filename} - missing 'version' key.")
                except Exception as e:
                    print(f"❌ Debug: Failed to read {filename}: {e}")
        
        print(f"📂 Prompt Registry load complete. Registry keys: {list(self.registry.keys())}")

    def get_prompt(self, version: str) -> dict:
        return self.registry.get(version)

    async def get_active_version(self) -> str:
        active = await redis_client.get("prompt:active_version")
        if active:
            return active.decode("utf-8")
        return "v1"

# --- THE FIX: Factory function to break circular imports ---
_registry_instance: Optional[PromptRegistry] = None

def get_registry() -> PromptRegistry:
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = PromptRegistry()
    return _registry_instance