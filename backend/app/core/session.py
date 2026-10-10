"""Anonymous local sessions via an HttpOnly cookie. Every query is scoped to the
caller's session, so one browser cannot read or delete another's data."""
import uuid
from datetime import datetime, timezone

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import Session

COOKIE = "ss_session"


async def current_session(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> Session:
    raw = request.cookies.get(COOKIE)
    sess = None
    if raw:
        try:
            sess = await db.get(Session, uuid.UUID(raw))
        except ValueError:
            sess = None
    if sess is None:
        sess = Session(preferences={})
        db.add(sess)
        await db.commit()
    else:
        sess.last_seen_at = datetime.now(timezone.utc)
        await db.commit()
    response.set_cookie(COOKIE, str(sess.id), httponly=True, samesite="lax", secure=get_settings().cookie_secure,
                        max_age=60 * 60 * 24 * 365, path="/")
    return sess
