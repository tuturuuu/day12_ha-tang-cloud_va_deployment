"""
Agent Railway-ready.
Railway inject PORT env var tự động — agent phải dùng os.getenv("PORT").
"""
import os
import time
from json import JSONDecodeError
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from utils.mock_llm import ask

app = FastAPI(title="Agent on Railway", version="1.0.0")
START_TIME = time.time()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "message": "AI Agent running on Railway!",
        "docs": "/docs",
        "health": "/health",
    }


@app.post("/ask")
async def ask_agent(request: Request):
    try:
        body = await request.json()
    except JSONDecodeError:
        raise HTTPException(400, "invalid JSON body")

    if not isinstance(body, dict):
        raise HTTPException(422, "JSON object body required")

    question = body.get("question", "")
    if not isinstance(question, str) or not question.strip():
        raise HTTPException(422, "question required")
    question = question.strip()

    return {
        "question": question,
        "answer": ask(question),
        "platform": "Railway",
    }


@app.get("/health")
def health():
    """
    Railway sẽ check endpoint này định kỳ.
    Trả về 200 = healthy. Non-200 = Railway restart container.
    """
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "platform": "Railway",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    # ✅ Railway inject PORT — PHẢI đọc từ env
    port = int(os.getenv("PORT", 8000))
    print(f"Starting on port {port} (from PORT env var)")
    uvicorn.run(app, host="0.0.0.0", port=port)
