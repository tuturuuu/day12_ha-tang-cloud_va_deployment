import json
import logging
import signal
import time
from datetime import datetime, timezone

import redis
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .auth import verify_api_key
from .config import settings
from .cost_guard import check_budget, estimate_cost_usd, record_spend
from .rate_limiter import check_rate_limit


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=True)


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("agent")
    logger.setLevel(settings.LOG_LEVEL.upper())
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger


logger = setup_logger()
r = redis.from_url(settings.REDIS_URL, decode_responses=True)

app = FastAPI(title=settings.APP_NAME)
START_TIME = time.time()
is_shutting_down = False


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class AskResponse(BaseModel):
    user_id: str
    question: str
    answer: str
    history_size: int
    cost_usd: float
    timestamp: str


def mock_llm_answer(question: str, history: list[str]) -> str:
    context_hint = ""
    if history:
        context_hint = f" | history_messages={len(history)}"
    return f"[mock-agent] I received: {question}{context_hint}"


def _sigterm_handler(signum, frame):
    del signum
    del frame
    global is_shutting_down
    is_shutting_down = True
    logger.info("received SIGTERM, draining in-flight requests")


signal.signal(signal.SIGTERM, _sigterm_handler)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    try:
        response: Response = await call_next(request)
    except Exception:
        logger.exception(f"request failed path={request.url.path}")
        raise

    duration_ms = round((time.time() - start) * 1000, 2)
    logger.info(
        json.dumps(
            {
                "event": "request",
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            }
        )
    )
    return response


@app.get("/health")
def health():
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - START_TIME, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready")
def ready():
    if is_shutting_down:
        raise HTTPException(status_code=503, detail="Shutting down")

    try:
        r.ping()
    except redis.RedisError as exc:
        raise HTTPException(status_code=503, detail="Redis unavailable") from exc

    return {"status": "ready"}


@app.post("/ask", response_model=AskResponse)
def ask(
    body: AskRequest,
    user_id: str = Depends(verify_api_key),
    _rate_limit: None = Depends(check_rate_limit),
):
    if is_shutting_down:
        raise HTTPException(status_code=503, detail="Server is shutting down")

    history_key = f"history:{user_id}"
    try:
        history = r.lrange(history_key, 0, -1)
    except redis.RedisError as exc:
        raise HTTPException(status_code=503, detail="Redis unavailable") from exc

    preflight_cost = estimate_cost_usd(body.question)
    check_budget(user_id, preflight_cost)

    answer = mock_llm_answer(body.question, history)
    final_cost = estimate_cost_usd(body.question, answer)
    check_budget(user_id, final_cost)
    record_spend(user_id, final_cost)

    user_message = json.dumps({"role": "user", "content": body.question}, ensure_ascii=True)
    assistant_message = json.dumps({"role": "assistant", "content": answer}, ensure_ascii=True)
    try:
        pipe = r.pipeline(transaction=True)
        pipe.rpush(history_key, user_message, assistant_message)
        pipe.ltrim(history_key, -settings.HISTORY_MAX_MESSAGES, -1)
        pipe.expire(history_key, 7 * 24 * 3600)
        pipe.execute()
        history_size = r.llen(history_key)
    except redis.RedisError as exc:
        raise HTTPException(status_code=503, detail="Redis unavailable") from exc

    return AskResponse(
        user_id=user_id,
        question=body.question,
        answer=answer,
        history_size=history_size,
        cost_usd=final_cost,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT)

