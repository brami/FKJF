"""Hilfen für Tests: die drei Stufen, die die Migration aus den bisherigen Gruppen anlegt."""

from seiten.models import Stufe

OEFFENTLICH = "Öffentlich"
FOERDERMITGLIEDER = "Fördermitglieder"
MITGLIEDER = "Mitglieder"
VORSTAND = "Vorstand"

RANG = {OEFFENTLICH: 0, FOERDERMITGLIEDER: 10, MITGLIEDER: 20, VORSTAND: 30}
STUFEN = list(RANG)


def stufe(name):
    """Stufe nach Name; Öffentlich ist keine Stufe (None)."""
    return None if name == OEFFENTLICH else Stufe.objects.get(name=name)


def formwert(name):
    """Wert des Stufen-Felds im Bearbeitungsformular."""
    s = stufe(name)
    return "" if s is None else str(s.pk)
