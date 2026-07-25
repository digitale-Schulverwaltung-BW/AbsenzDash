from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.webuntis_client import WebUntisClient
from app.models.classreg_category import ClassregCategory


async def sync_kategorien(client: WebUntisClient, db: AsyncSession) -> None:
    """getClassregCategories + getClassregCategoryGroups -> classreg_category (TECH-SPEC.md Abschnitt 1.2)."""
    categories = await client.call("getClassregCategories", {})
    groups = await client.call("getClassregCategoryGroups", {})
    group_name_by_id = {group["id"]: group["name"] for group in groups}

    existing = (await db.execute(select(ClassregCategory))).scalars().all()
    by_webuntis_id = {kategorie.webuntis_id: kategorie for kategorie in existing}

    for row in categories:
        kategorie = by_webuntis_id.get(row["id"])
        if kategorie is None:
            kategorie = ClassregCategory(webuntis_id=row["id"], name=row["name"])
            db.add(kategorie)
        else:
            kategorie.name = row["name"]
        kategorie.long_name = row.get("longName")
        kategorie.group_name = group_name_by_id.get(row.get("groupId"))

    await db.commit()
