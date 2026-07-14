import os
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from skinmate import db
from skinmate.app.turn import process_turn
from skinmate.chat.orchestrator import TurnResult
from skinmate.config import settings
from skinmate.llm.base import LLMProvider
from skinmate.llm.nvidia import NvidiaProvider

app = FastAPI(title="skinmate")

# static 폴더 경로 설정 및 생성 보장
current_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(current_dir, "static")
os.makedirs(static_dir, exist_ok=True)

# 정적 파일 마운트
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def read_index() -> FileResponse:
    return FileResponse(os.path.join(static_dir, "index.html"))


class ChatRequest(BaseModel):
    user_id: int
    utterance: str
    history: list[str] | None = None
    season: str | None = None


def _get_provider() -> LLMProvider:
    return NvidiaProvider(api_key=settings.openai_api_key, model=settings.llm_model)


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
