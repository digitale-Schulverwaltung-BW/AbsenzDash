from app.models.base import Base
from app.models.bereich import Bereich, bereich_klasse
from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.schueler import Schueler

__all__ = ["Base", "Bereich", "bereich_klasse", "ExcuseStatus", "Fehlzeit", "Klasse", "Schueler"]
