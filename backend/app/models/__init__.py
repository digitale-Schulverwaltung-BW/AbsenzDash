from app.models.base import Base
from app.models.bereich import Bereich, bereich_klasse
from app.models.classreg_category import ClassregCategory
from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.schueler import Schueler

__all__ = [
    "Base",
    "Bereich",
    "bereich_klasse",
    "ClassregCategory",
    "ExcuseStatus",
    "Fehlzeit",
    "Klasse",
    "KlassenbuchEintrag",
    "Schueler",
]
