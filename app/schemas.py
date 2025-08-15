from pydantic import BaseModel
from typing import List, Optional

class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str

class ChatRequestResponse(BaseModel):
    audio_url: Optional[str]
    transcript: str
    llm_response: str
    history: List[ChatMessage]

class LLMQueryResponse(BaseModel):
    audio_url: Optional[str]
    transcript: str
    llm_response: str
