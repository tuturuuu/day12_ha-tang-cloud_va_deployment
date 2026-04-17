import time

import redis
from fastapi import HTTPException

from .config import settings


r = redis.from_url(settings.REDIS_URL, decode_responses=True)


def check_rate_limit(user_id: str) -> None:
    window_key = f"rate:{user_id}"
    now = time.time()
    window_start = now - settings.RATE_LIMIT_WINDOW_SECONDS

    try:
        pipe = r.pipeline(transaction=True)
        pipe.zremrangebyscore(window_key, 0, window_start)
        pipe.zcard(window_key)
        _, count = pipe.execute()

        if count >= settings.RATE_LIMIT_PER_MINUTE:
            oldest = r.zrange(window_key, 0, 0, withscores=True)
            retry_after = settings.RATE_LIMIT_WINDOW_SECONDS
            if oldest:
                retry_after = max(
                    1,
                    int(oldest[0][1] + settings.RATE_LIMIT_WINDOW_SECONDS - now) + 1,
                )
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )

        pipe = r.pipeline(transaction=True)
        pipe.zadd(window_key, {str(now): now})
        pipe.expire(window_key, settings.RATE_LIMIT_WINDOW_SECONDS)
        pipe.execute()
    except redis.RedisError as exc:
        raise HTTPException(status_code=503, detail="Redis unavailable") from exc
