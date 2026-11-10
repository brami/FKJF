from django.db import models


class Stufe(models.IntegerChoices):
    OEFFENTLICH = 0, "Öffentlich"
    FOERDERMITGLIEDER = 1, "Fördermitglieder"
    MITGLIEDER = 2, "Mitglieder"
    VORSTAND = 3, "Vorstand"


# Name der Django-Gruppe -> Stufe. Die Gruppen werden per Migration angelegt.
GRUPPE_ZU_STUFE = {
    "Fördermitglieder": Stufe.FOERDERMITGLIEDER,
    "Mitglieder": Stufe.MITGLIEDER,
    "Vorstand": Stufe.VORSTAND,
}
