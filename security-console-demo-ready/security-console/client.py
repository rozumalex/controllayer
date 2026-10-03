import os
import httpx

DEFAULT_URL = os.getenv("CONTROL_LAYER_URL", "http://127.0.0.1:9000")


class ControlLayerClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or DEFAULT_URL).rstrip("/")

    def evaluate(
        self,
        prompt: str,
        context: str = "",
        identity: str = "judge",
        permission: str = "STANDARD",
        data_sensitivity: str = "PUBLIC",
        model: str = "default",
        max_tokens: int = 256,
    ) -> dict:
        payload = {
            "prompt": prompt,
            "context": context,
            "identity": identity,
            "permission": permission,
            "data_sensitivity": data_sensitivity,
            "model": model,
            "max_tokens": max_tokens,
        }
        with httpx.Client(timeout=20.0) as client:
            response = client.post(f"{self.base_url}/evaluate", json=payload)
            response.raise_for_status()
            return response.json()

    def metrics(self) -> dict:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"{self.base_url}/metrics")
            response.raise_for_status()
            return response.json()

    def audit(self, limit: int = 50) -> list[dict]:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"{self.base_url}/audit", params={"limit": limit})
            response.raise_for_status()
            return response.json()

    def reset(self) -> dict:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(f"{self.base_url}/reset")
            response.raise_for_status()
            return response.json()
