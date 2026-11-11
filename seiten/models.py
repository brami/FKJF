import re
from pathlib import Path
from uuid import uuid4

import nh3
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.contrib.auth.models import Group
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import Truncator
from simple_history.models import HistoricalRecords

from .bilder import fassungen, ist_bildname, pruefe_bild
from .stufen import OEFFENTLICH

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


class Stufe(models.Model):
    """Eine Stufe (Gruppe) – frei benennbar, nach Rang geordnet.

    Wer einer Stufe angehört, sieht alle Seiten dieser und aller niedrigeren Stufen.
    „Öffentlich“ (ohne Anmeldung) ist fest die unterste Stufe und hat keinen Eintrag.
    Zu jeder Stufe gehört eine gleichnamige Django-Gruppe; über sie werden Personen
    zugeordnet.
    """

    name = models.CharField(max_length=60, unique=True)
    rang = models.PositiveSmallIntegerField(
        unique=True, validators=[MinValueValidator(1)],
        help_text="Höhere Zahl = höhere Stufe. Abstände (10, 20, 30 …) lassen Platz für spätere Stufen.",
    )
    darf_bearbeiten = models.BooleanField(
        "darf bearbeiten", default=False,
        help_text="Seiten anlegen und ändern, Benutzer verwalten, Versionsverlauf, Newsletter. "
                  "Für diese Stufe ist die Zwei-Faktor-Anmeldung Pflicht.",
    )
    gruppe = models.OneToOneField(Group, on_delete=models.PROTECT, related_name="stufe",
                                  editable=False)

    class Meta:
        verbose_name = "Stufe"
        verbose_name_plural = "Stufen"
        ordering = ["rang"]

    def __str__(self):
        return self.name

    def clean(self):
        andere = Group.objects.filter(name=self.name)
        if self.gruppe_id:
            andere = andere.exclude(pk=self.gruppe_id)
        if andere.filter(stufe__isnull=False).exists() or (self.gruppe_id and andere.exists()):
            raise ValidationError({"name": "Diesen Namen trägt bereits eine andere Gruppe."})

    def save(self, *args, **kwargs):
        # Gruppe anlegen bzw. mit umbenennen
        if self.gruppe_id:
            if self.gruppe.name != self.name:
                self.gruppe.name = self.name
                self.gruppe.save(update_fields=["name"])
        else:
            self.gruppe, _ = Group.objects.get_or_create(name=self.name)
        super().save(*args, **kwargs)

    @classmethod
    def voreinstellung(cls):
        """Vorschlag für neue Seiten: die höchste Stufe ohne Bearbeitungsrecht."""
        return cls.objects.filter(darf_bearbeiten=False).order_by("-rang").first()


class Webseite(models.Model):
    """Name und feste Texte der Webseite (genau ein Eintrag, Pflege durch Administratoren).

    Damit lässt sich die Anwendung ohne Änderung am Quellcode für andere Vereine
    oder Zwecke verwenden.
    """

    name = models.CharField(
        max_length=100, default="Meine Webseite",
        help_text="Kopfzeile, Fenstertitel, Betreff der E-Mails, Eintrag in der Authenticator-App.",
    )
    slogan = models.CharField(max_length=200, blank=True, help_text="Unter dem Namen in der Kopfzeile.")
    inhaber = models.CharField(
        "Inhaber", max_length=200, blank=True,
        help_text="Vollständiger Name für die Fußzeile (© …), z. B. mit „e. V.“. Leer = Name.",
    )
    ansprechpartner = models.CharField(
        "Ansprechpartner", max_length=100, default="den Vorstand",
        help_text="Ergänzt „Für ein Konto wenden Sie sich bitte an …“, z. B. „den Vorstand“.",
    )
    unterschrift = models.CharField(
        max_length=100, default="Der Vorstand",
        help_text="Unter den E-Mails, z. B. der Einladung.",
    )
    antwort_an = models.EmailField(
        "Weitere Antwortadresse", blank=True,
        help_text="Antworten auf einen Newsletter gehen an die versendende Person und an diese "
                  "Adresse, z. B. die des Vorstands.",
    )

    class Meta:
        verbose_name = "Einstellungen der Webseite"
        verbose_name_plural = "Einstellungen der Webseite"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.pk = 1   # immer genau ein Eintrag
        super().save(*args, **kwargs)

    @classmethod
    def aktuell(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def fuss(self):
        return self.inhaber or self.name


class Seite(models.Model):
    titel = models.CharField(max_length=200)
    datum = models.DateField(default=timezone.localdate)
    stufe = models.ForeignKey(
        Stufe, verbose_name="Sichtbar für", null=True, blank=True,
        on_delete=models.PROTECT, related_name="seiten",
        help_text=f"Die Seite sehen diese Stufe und alle höheren. Leer = {OEFFENTLICH} (ohne Anmeldung).",
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

    @property
    def stufe_name(self):
        return self.stufe.name if self.stufe_id else OEFFENTLICH

    def vorschau(self, woerter=40):
        # Absätze, Listenpunkte usw. durch Leerzeichen trennen, damit Wörter nicht zusammenkleben
        text = re.sub(r"<(/(p|h[1-6]|li|td|th|blockquote)|br\s*/?)>", " ", self.inhalt or "")
        return Truncator(" ".join(strip_tags(text).split())).words(woerter, truncate=" …")

    # Anhänge aufgeteilt: Bilder (Titelbild zuerst) und übrige Dateien.
    # Arbeiten mit .all(), damit prefetch_related("anhaenge") genutzt wird.
    def bilder(self):
        bilder = [a for a in self.anhaenge.all() if a.ist_bild]
        return sorted(bilder, key=lambda a: (not a.titelbild, a.pk))

    def titelbild(self):
        bilder = self.bilder()
        return bilder[0] if bilder else None

    def galerie(self):
        return self.bilder()[1:]

    def dateien(self):
        return [a for a in self.anhaenge.all() if not a.ist_bild]


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
            pruefe_bild,
        ],
    )
    dateiname = models.CharField(max_length=255, editable=False)
    bezeichnung = models.CharField(max_length=200, blank=True)
    # Bilder: verkleinerte Fassungen, beim Hochladen erzeugt (ohne Metadaten)
    ist_bild = models.BooleanField(default=False, editable=False)
    titelbild = models.BooleanField(
        "Titelbild", default=False,
        help_text="Erscheint oben auf der Seite und als Vorschau auf der Startseite. "
                  "Ohne Auswahl ist es das erste Bild.",
    )
    bild = models.FileField(storage=private_storage, upload_to=anhang_pfad, blank=True, editable=False)
    vorschaubild = models.FileField(storage=private_storage, upload_to=anhang_pfad, blank=True,
                                    editable=False)
    hochgeladen = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords(verbose_name="Fassung")

    class Meta:
        verbose_name = "Anhang"
        verbose_name_plural = "Anhänge"
        ordering = ["pk"]

    def __str__(self):
        return self.bezeichnung or self.dateiname

    def save(self, *args, **kwargs):
        # Neu hochgeladenes Bild: ohne Metadaten neu schreiben und verkleinern
        if self.datei and not self.datei._committed and ist_bildname(self.datei.name):
            original = self.datei.name
            f = fassungen(self.datei.file, original)
            self.dateiname = Path(original).stem[:240] + Path(f["datei"].name).suffix
            self.datei = f["datei"]
            self.bild = f["bild"]
            self.vorschaubild = f["vorschau"]
            self.ist_bild = True
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("anhang", args=[self.pk])

    def bild_url(self):
        return reverse("anhang_variante", args=[self.pk, "bild"])

    def vorschau_url(self):
        return reverse("anhang_variante", args=[self.pk, "vorschau"])


@models.signals.post_delete.connect
def _anhang_datei_loeschen(sender, instance, **kwargs):
    """Beim Löschen eines Anhangs (auch über das Löschen der Seite) die Datei entfernen."""
    if sender is Anhang:
        for feld in (instance.datei, instance.bild, instance.vorschaubild):
            if feld:
                feld.delete(save=False)


class Profil(models.Model):
    """Zusätzliche Angaben zu einem Konto: Vereinsadresse (Postfach) und Zustellung.

    Die externe Adresse ist User.email. Sie ist immer vorhanden und wird für
    „Passwort vergessen“ und Einladungen verwendet. Die Vereinsadresse gibt es nur
    bei Konten mit Postfach auf dem Mailserver des Vereins; dessen Passwort ist das
    der Webseite (Dovecot liest die Sicht „dovecot_benutzer“).
    """

    class Zustellung(models.TextChoices):
        EXTERN = "extern", "an die externe Adresse"
        VEREIN = "verein", "an die Vereinsadresse"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="profil")
    vereins_email = models.EmailField(
        "Vereinsadresse (Postfach)", blank=True, null=True, unique=True,
        help_text="Nur bei Konten mit Postfach auf dem Mailserver des Vereins. "
                  "Anmelden geht auch mit dieser Adresse.",
    )
    zustellung = models.CharField(
        "Vereinsmails (z. B. Newsletter)", max_length=10,
        choices=Zustellung.choices, default=Zustellung.EXTERN,
        help_text="„Passwort vergessen“ und Einladungen gehen immer an die externe Adresse.",
    )

    class Meta:
        verbose_name = "Profil"
        verbose_name_plural = "Profile"

    def __str__(self):
        return f"Profil von {self.user}"

    def save(self, *args, **kwargs):
        self.vereins_email = (self.vereins_email or "").strip().lower() or None
        if not self.vereins_email:
            self.zustellung = self.Zustellung.EXTERN
        super().save(*args, **kwargs)


def profil_von(user) -> "Profil":
    profil, _ = Profil.objects.get_or_create(user=user)
    return profil


def zustelladresse(user) -> str:
    """Adresse für Vereinsmails (Newsletter): nach Wahl der Person."""
    profil = getattr(user, "profil", None)
    if profil and profil.vereins_email and profil.zustellung == Profil.Zustellung.VEREIN:
        return profil.vereins_email
    return user.email


@models.signals.post_delete.connect
def _stufe_gruppe_loeschen(sender, instance, **kwargs):
    """Wird eine Stufe gelöscht, verschwindet auch ihre Gruppe (und damit die Zuordnungen)."""
    if sender is Stufe and instance.gruppe_id:
        Group.objects.filter(pk=instance.gruppe_id).delete()


class Versand(models.Model):
    """Ein Newsletter: eine Seite, verschickt an ausgewählte Stufen."""

    class Modus(models.TextChoices):
        VOLLTEXT = "volltext", "Seite in der E-Mail"
        LINK = "link", "Nur Vorschau und Link"

    class Status(models.TextChoices):
        LAEUFT = "laeuft", "läuft"
        FERTIG = "fertig", "abgeschlossen"
        ABGEBROCHEN = "abgebrochen", "abgebrochen"

    seite = models.ForeignKey(Seite, on_delete=models.SET_NULL, null=True, related_name="versaende")
    titel = models.CharField(max_length=200)   # bleibt, auch wenn die Seite gelöscht wird
    absender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                 related_name="+")
    modus = models.CharField(max_length=10, choices=Modus.choices, default=Modus.LINK)
    ankuendigung = models.TextField("Ankündigung", blank=True)
    mit_anhaengen = models.BooleanField("Anhänge mitsenden", default=False)
    stufen = models.ManyToManyField(Stufe, blank=True, related_name="+")
    ohne_stufe = models.BooleanField("Konten ohne Stufe", default=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.LAEUFT)
    erstellt = models.DateTimeField(auto_now_add=True)
    weiter_ab = models.DateTimeField(null=True, blank=True)   # Pause nach der Probe / Abstand
    beendet = models.DateTimeField(null=True, blank=True)
    abgebrochen_von = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = "Newsletter-Versand"
        verbose_name_plural = "Newsletter-Versände"
        ordering = ["-erstellt"]

    def __str__(self):
        return f"{self.titel} ({self.erstellt:%d.%m.%Y %H:%M})"

    def get_absolute_url(self):
        return reverse("newsletter_status", args=[self.pk])

    def zaehlung(self):
        z = dict(self.empfaenge.values_list("status").annotate(n=models.Count("pk")))
        return {s: z.get(s, 0) for s in Empfang.Status.values}

    def in_pause(self, jetzt=None):
        """Probe ist verschickt, die Pause läuft noch, an andere ging noch nichts."""
        jetzt = jetzt or timezone.now()
        return (self.status == self.Status.LAEUFT and self.weiter_ab is not None
                and self.weiter_ab > jetzt
                and self.empfaenge.filter(reihenfolge=0, zeit__isnull=False).exists()
                and not self.empfaenge.filter(reihenfolge__gt=0, zeit__isnull=False).exists())


class Empfang(models.Model):
    """Ein Empfänger eines Versands (Reihenfolge 0 = Probe an die versendende Person)."""

    class Status(models.TextChoices):
        OFFEN = "offen", "wartet"
        GESENDET = "gesendet", "gesendet"
        FEHLER = "fehler", "Fehler"
        OHNE_ADRESSE = "ohne", "keine E-Mail-Adresse"
        NICHT_GESENDET = "nicht", "nicht gesendet (abgebrochen)"

    versand = models.ForeignKey(Versand, on_delete=models.CASCADE, related_name="empfaenge")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                             related_name="+")
    name = models.CharField(max_length=200)
    adresse = models.EmailField(blank=True)
    stufe = models.CharField(max_length=60, blank=True)
    reihenfolge = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OFFEN)
    fehler = models.TextField(blank=True)
    zeit = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Empfänger"
        verbose_name_plural = "Empfänger"
        ordering = ["reihenfolge", "pk"]

    def __str__(self):
        return f"{self.name} <{self.adresse}>"
