from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.audit_log import AuditLog
from app.models.nutzer import ROLLEN, Nutzer


async def get_wordpress_proxy_nutzer(
    x_wordpress_secret: Annotated[str, Header(alias="X-WordPress-Secret")],
    x_wordpress_user: Annotated[str, Header(alias="X-WordPress-User")],
    x_wordpress_email: Annotated[str, Header(alias="X-WordPress-Email")],
    x_wordpress_name: Annotated[str, Header(alias="X-WordPress-Name")],
    x_wordpress_role: Annotated[str, Header(alias="X-WordPress-Role")],
    db: Annotated[AsyncSession, Depends(get_db)],
    x_wordpress_webuntis_code: Annotated[str | None, Header(alias="X-WordPress-WebUntis-Code")] = None,
) -> Nutzer:
    if not hmac.compare_digest(x_wordpress_secret, settings.wordpress_proxy_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid WordPress proxy secret")

    if x_wordpress_role not in ROLLEN:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown role: {x_wordpress_role}")

    webuntis_teacher_id = int(x_wordpress_webuntis_code) if x_wordpress_webuntis_code else None

    result = await db.execute(select(Nutzer).where(Nutzer.wp_user_id == x_wordpress_user))
    nutzer = result.scalar_one_or_none()

    if nutzer is None:
        nutzer = Nutzer(
            wp_user_id=x_wordpress_user,
            email=x_wordpress_email,
            name=x_wordpress_name,
            rolle=x_wordpress_role,
            webuntis_teacher_id=webuntis_teacher_id,
        )
        db.add(nutzer)
        aktion = "wordpress_proxy_created"
    else:
        nutzer.email = x_wordpress_email
        nutzer.name = x_wordpress_name
        nutzer.rolle = x_wordpress_role
        nutzer.webuntis_teacher_id = webuntis_teacher_id
        aktion = "wordpress_proxy_updated"

    await db.flush()

    db.add(
        AuditLog(
            user_id=nutzer.id,
            aktion=aktion,
            resource_typ="nutzer",
            resource_id=str(nutzer.id),
            details={"quelle": "wordpress_proxy"},
        )
    )
    await db.commit()
    await db.refresh(nutzer)
    return nutzer
