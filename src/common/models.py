from pydantic import BaseModel, Field


class AnonymizeRequest(BaseModel):
    text: str = Field(min_length=1)
    session_id: str | None = None
    language: str = "en"


class AnonymizeResponse(BaseModel):
    session_id: str
    anonymized_text: str
    is_valid: bool
    risk_score: float


class DeanonymizeRequest(BaseModel):
    text: str = Field(min_length=1)
    session_id: str
    sanitized_prompt: str | None = None


class DeanonymizeResponse(BaseModel):
    session_id: str
    deanonymized_text: str
    is_valid: bool
    risk_score: float


class ChatSafeRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    language: str = "en"


class ChatSafeResponse(BaseModel):
    session_id: str
    model: str
    anonymized_prompt: str
    raw_model_output: str
    final_output: str


class PresidioRequest(BaseModel):
    text: str = Field(min_length=1)


class PresidioResponse(BaseModel):
    anonymized_text: str
    entities: list[dict]
