from app.models.abteilung import Abteilung
from app.models.audit_log import AuditLog
from app.models.ausnahme import Ausnahme
from app.models.base import Base
from app.models.bereich import Bereich, bereich_klasse
from app.models.classreg_category import ClassregCategory
from app.models.einstellung import Einstellung
from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp, massnahmen_typ_regel
from app.models.nutzer import ROLLEN, Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.models.nutzer_klasse import NutzerKlasse
from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand
from app.models.schwellwert_regel import SchwellwertRegel
from app.models.schwellwert_stufe import SchwellwertStufe

__all__ = [
    "Abteilung",
    "AuditLog",
    "Ausnahme",
    "Base",
    "Bereich",
    "bereich_klasse",
    "ClassregCategory",
    "Einstellung",
    "ExcuseStatus",
    "Fehlzeit",
    "Klasse",
    "KlassenbuchEintrag",
    "Massnahme",
    "MassnahmenTyp",
    "massnahmen_typ_regel",
    "Nutzer",
    "nutzer_bereich",
    "NutzerKlasse",
    "ROLLEN",
    "Schueler",
    "SchuelerZaehlerstand",
    "SchwellwertRegel",
    "SchwellwertStufe",
]
