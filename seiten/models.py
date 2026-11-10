from pathlib import Path
from uuid import uuid4

import nh3
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.validators import FileExtensionValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import Truncator
from simple_history.models import HistoricalRecords

from .stufen import Stufe

# Erlaubte HTML-Elemente im Seiteninhalt; alles andere entfernt nh3.
ERLAUBTE_TAGS = {
    "p", "br", "strong", "b", "em", "i", "u", "s", "sub", "sup",
    "h2", "h3", "h4", "ul", "ol", "li", "blockquote", "hr",
    "a", "table", "thead", "tbody", "tr", "th", "td", "caption",
}
ERLAUBTE_ATTRIBUTE = {
    "a": {"href", "title"},
    "th": {"colspan", "rowspan"},
    "td": {"colspan", "rowspan"},
}


def bereinige_html(html: str) -> str:
    return nh3.clean(
        html or "",
        tags=ERLAUBTE_TAGS,
        attributes=ERLAUBTE_ATTRIBUTE,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
    )


def private_storage():
    """Ablage für Anhänge außerhalb des Webverzeichnisses (ohne öffentliche URL).

    Als Funktion angegeben, damit der Pfad aus den Einstellungen kommt und nicht
    in den Migrationen festgeschrieben wird.
    """
    return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT, base_url=None)


class Seite(models.Model):
    titel = models.CharField(max_length=200)
    datum = models.DateField(default=timezone.localdate)
    stufe = models.IntegerField(
        "Sichtbar für", choices=Stufe.choices, default=Stufe.MITGLIEDER,
        help_text="Die Seite sehen diese Gruppe und alle höheren.",
    )
    inhalt = models.TextField(blank=True)
    erstellt = models.DateTimeField(auto_now_add=True)
    geaendert = models.DateTimeField(auto_now=True)

    history = HistoricalRecords(verbose_name="Fassung")

    class Meta:
        verbose_name = "Seite"
        verbose_name_plural = "Seiten"
        ordering = ["-datum", "-pk"]

    def __str__(self):
        return self.titel

    def save(self, *args, **kwargs):
        self.inhalt = bereinige_html(self.inhalt)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("seite", args=[self.pk])

    def vorschau(self, woerter=40):
        return Truncator(strip_tags(self.inhalt)).words(woerter, truncate=" …")


def anhang_pfad(instance, filename):
    # Zufälliger Name verhindert Kollisionen und erratbare Pfade;
    # der ursprüngliche Name bleibt im Feld "dateiname" erhalten.
    if not instance.dateiname:
        instance.dateiname = Path(filename).name[:255]
    endung = Path(filename).suffix.lower()
    return f"anhaenge/{uuid4().hex}{endung}"


def pruefe_groesse(datei):
    if datei.size > settings.ANHANG_MAX_BYTES:
        mb = settings.ANHANG_MAX_BYTES // (1024 * 1024)
        raise ValidationError(f"Die Datei ist größer als {mb} MB.")


class Anhang(models.Model):
    seite = models.ForeignKey(Seite, on_delete=models.CASCADE, related_name="anhaenge")
    datei = models.FileField(
        storage=private_storage,
        upload_to=anhang_pfad,
        validators=[
            FileExtensionValidator(allowed_extensions=settings.ANHANG_ENDUNGEN),
            pruefe_groesse,
        ],
    )
    dateiname = models.CharField(max_length=255, editable=False)
    bezeichnung = models.CharField(max_length=200, blank=True)
    hochgeladen = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords(verbose_name="Fassung")

    class Meta:
        verbose_name = "Anhang"
        verbose_name_plural = "Anhänge"
        ordering = ["pk"]

    def __str__(self):
        return self.bezeichnung or self.dateiname

    def get_absolute_url(self):
        return reverse("anhang", args=[self.pk])


@models.signals.post_delete.connect
def _anhang_datei_loeschen(sender, instance, **kwargs):
    """Beim Löschen eines Anhangs (auch über das Löschen der Seite) die Datei entfernen."""
    if sender is Anhang and instance.datei:
        instance.datei.delete(save=False)
