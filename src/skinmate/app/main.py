"""API 표면(FastAPI) — POST /chat. 요청당 커넥션을 열어 process_turn(2.1)에 위임한다."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from skinmate import db
from skinmate.app.turn import process_turn
from skinmate.chat.orchestrator import TurnResult
from skinmate.config import settings
from skinmate.llm.gemini import GeminiProvider

app = FastAPI(title="skinmate")


class ChatRequest(BaseModel):
    user_id: int
    utterance: str
    history: list[str] | None = None
    season: str | None = None


def _get_provider() -> GeminiProvider:
    return GeminiProvider(api_key=settings.gemini_api_key, model=settings.llm_model)


@app.post("/chat")
def chat(req: ChatRequest) -> TurnResult:
    provider = _get_provider()
    conn = db.connect()
    try:
        result = process_turn(
            conn,
            provider,
            req.user_id,
            req.utterance,
            history=req.history,
            season=req.season,
        )
    finally:
        conn.close()
    return result
