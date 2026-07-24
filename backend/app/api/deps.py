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


def _decode_header_value(value: str) -> str:
    """Recover UTF-8 header values from Starlette's mandatory Latin-1 decode.

    Starlette decodes all incoming HTTP header bytes as Latin-1 (per RFC 7230)
    before this code ever sees them. If the sender (e.g. a PHP/UTF-8
    WordPress proxy) actually sent UTF-8 bytes, that Latin-1 decode produces
    mojibake. Re-encode to recover the original bytes, then try UTF-8 first;
    fall back to the Latin-1-decoded value unchanged if it's not valid UTF-8
    (the sender genuinely sent Latin-1, or the value is plain ASCII where
    both interpretations agree).
    """
    raw_bytes = value.encode("latin-1")
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return value


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
    nutzer_name = _decode_header_value(x_wordpress_name)

    result = await db.execute(select(Nutzer).where(Nutzer.wp_user_id == x_wordpress_user))
    nutzer = result.scalar_one_or_none()

    if nutzer is None:
        nutzer = Nutzer(
            wp_user_id=x_wordpress_user,
            email=x_wordpress_email,
            name=nutzer_name,
            rolle=x_wordpress_role,
            webuntis_teacher_id=webuntis_teacher_id,
        )
        db.add(nutzer)
        aktion = "wordpress_proxy_created"
    else:
        nutzer.email = x_wordpress_email
        nutzer.name = nutzer_name
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
