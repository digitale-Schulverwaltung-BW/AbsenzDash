from __future__ import annotations

import re
import unicodedata

_UMLAUT_MAP = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}
)


def build_export_filename(nachname: str, vorname: str) -> str:
    """Baut einen sicheren Dateinamen fuer den Content-Disposition-Header: deutsche
    Umlaute/Eszett explizit transliteriert, alle anderen diakritischen Zeichen per
    NFKD-Normalisierung auf den Basis-Buchstaben reduziert, verbleibende
    Nicht-ASCII-/Sonderzeichen (inkl. Leerzeichen) durch '-' ersetzt."""
    raw = f"{nachname}_{vorname}_export".translate(_UMLAUT_MAP)
    ascii_normalized = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^A-Za-z0-9_]+", "-", ascii_normalized).strip("-")
    return f"{normalized}.pdf"
