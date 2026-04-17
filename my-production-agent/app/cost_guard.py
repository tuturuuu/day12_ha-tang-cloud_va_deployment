from __future__ import annotations

from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from .config import settings


r = redis.from_url(settings.REDIS_URL, decode_responses=True)


def _period_key(user_id: str) -> str:
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    return f"budget:{user_id}:{period}"


def estimate_cost_usd(question: str, answer: str | None = None) -> float:
    input_tokens = max(1, len(question.split()) * 2)
    output_tokens = max(0, len(answer.split()) * 2) if answer else 0
    input_cost = (input_tokens / 1000) * settings.COST_PER_1K_INPUT_TOKENS
    output_cost = (output_tokens / 1000) * settings.COST_PER_1K_OUTPUT_TOKENS
    return round(input_cost + output_cost, 6)


def check_budget(user_id: str, estimated_cost_usd: float = 0.0) -> None:
    try:
        current_spend = float(r.get(_period_key(user_id)) or 0.0)
    except redis.RedisError as exc:
        raise HTTPException(status_code=503, detail="Redis unavailable") from exc

    projected = current_spend + estimated_cost_usd
    if projected > settings.MONTHLY_BUDGET_USD:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Monthly budget exceeded",
                "current_spend_usd": round(current_spend, 6),
                "projected_spend_usd": round(projected, 6),
                "budget_usd": settings.MONTHLY_BUDGET_USD,
            },
        )


def record_spend(user_id: str, amount_usd: float) -> float:
    key = _period_key(user_id)
    try:
        pipe = r.pipeline(transaction=True)
        pipe.incrbyfloat(key, amount_usd)
        pipe.expire(key, 35 * 24 * 3600)
        total_spend, _ = pipe.execute()
        return float(total_spend)
    except redis.RedisError as exc:
        raise HTTPException(status_code=503, detail="Redis unavailable") from exc

