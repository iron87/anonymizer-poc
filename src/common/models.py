from pydantic import BaseModel, Field


class AgentViaPlanoRequest(BaseModel):
    message: str = Field(min_length=1)
    model: str = "local/llama3.2"
    session_id: str | None = None


class AgentViaPlanoResponse(BaseModel):
    request_id: str
    model: str
    content: str
    upstream: str



class PresidioResponse(BaseModel):
    anonymized_text: str
    entities: list[dict]
