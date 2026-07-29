from __future__ import annotations

from app.integrations.webuntis_client import WebUntisClient
from app.schemas.admin import WebUntisTeacherOut


async def list_teachers(client: WebUntisClient) -> list[WebUntisTeacherOut]:
    """getTeachers -> {id, kuerzel}[], nur aktive Lehrkraefte, alphabetisch nach Kuerzel.

    `name` ist bei dieser Schule live verifiziert das Lehrerkuerzel (2-9 Buchstaben,
    meist 3), nicht die numerische ID -- siehe Design-Dok Abschnitt "Live-Verifikation".
    """
    rows = await client.call("getTeachers", {})
    teachers = [
        WebUntisTeacherOut(id=row["id"], kuerzel=row["name"]) for row in rows if row.get("active", True)
    ]
    return sorted(teachers, key=lambda t: t.kuerzel)
