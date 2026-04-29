import os

import httpx


class OllamaClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    async def chat(
        self,
        model: str,
        user_message: str,
        system_prompt: str | None = None,
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {})
        content = message.get("content", "")
        return content
