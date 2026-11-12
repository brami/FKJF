"""Newsletter: eine Seite per E-Mail an ausgewählte Stufen verschicken.

Ablauf eines Versands
1. Die versendende Person wählt Stufen, „Seite in der E-Mail“ oder „nur Link“, eine
   Ankündigung und ob Anhänge mitgehen. Die Empfängerliste wird sofort festgeschrieben.
2. Der Dienst (manage.py newsletter_dienst) schickt zuerst eine Probe an die
   versendende Person, wartet FV_NEWSLETTER_PAUSE Sekunden und schickt dann jede Mail
   einzeln im Abstand von FV_NEWSLETTER_ABSTAND Sekunden – höchste Stufe zuerst.
3. Abbrechen ist jederzeit möglich; vor jeder Mail wird der Status neu gelesen.
"""

import html as htmlmod
import re
from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.views.decorators.http import require_http_methods, require_POST

from . import konto, rechte
from .bearbeiten import nur_vorstand
from .models import Empfang, Kreis, Seite, Stufe, Versand, Webseite, zustelladresse
from .stufen import OEFFENTLICH_RANG

HERZSCHLAG = "fv_newsletter_dienst"


# ------------------------------------------------------------------ Empfänger

def stufen_fuer(seite):
    """Stufen, an die die Seite gehen darf: ihre eigene und alle höheren."""
    rang = seite.stufe.rang if seite.stufe_id else OEFFENTLICH_RANG
    return Stufe.objects.filter(rang__gte=rang).order_by("-rang")


def empfaenger(seite, stufen, ohne_stufe=False, ausser=None, kreise=()):
    """Aktive Konten in den gewählten Stufen und Kreisen, höchste Stufe zuerst.

    Konten ohne Stufe nur bei öffentlichen Seiten. Immer nur Personen, die die Seite
    sehen dürfen (Stufe und Kreis der Seite). Liefert Liste von (user, stufenname).
    """
    erlaubt = set(stufen_fuer(seite).values_list("pk", flat=True))
    stufen = [s for s in stufen if s.pk in erlaubt]
    kreise = list(kreise)
    User = get_user_model()
    bedingung = Q(groups__stufe__in=stufen) | Q(kreise__in=kreise)
    if ohne_stufe and not seite.stufe_id:
        bedingung |= ~Q(pk__in=User.objects.filter(groups__stufe__isnull=False).values("pk"))
    qs = (User.objects.filter(is_active=True).filter(bedingung)
          .filter(pk__in=rechte.leser(seite).values("pk")).distinct()
          .select_related("profil")
          .annotate(rang=Max("groups__stufe__rang", filter=Q(groups__stufe__in=stufen))))
    if ausser is not None:
        qs = qs.exclude(pk=ausser.pk)
    namen = {s.rang: s.name for s in stufen}
    kreisname = {}
    if kreise:
        for k in kreise:
            for uid in k.personen.values_list("pk", flat=True):
                kreisname.setdefault(uid, f"Kreis {k.name}")
    liste = sorted(qs, key=lambda u: (-(u.rang or 0), u.last_name.lower(), u.first_name.lower(),
                                      u.username.lower()))
    return [(u, namen.get(u.rang) or kreisname.get(u.pk, "ohne Stufe")) for u in liste]


def anzeigename(user):
    return user.get_full_name() or user.username


@transaction.atomic
def versand_anlegen(seite, absender, *, modus, ankuendigung, mit_anhaengen, stufen, ohne_stufe,
                    kreise=()):
    v = Versand.objects.create(
        seite=seite, titel=seite.titel, absender=absender, modus=modus,
        ankuendigung=ankuendigung.strip(), mit_anhaengen=mit_anhaengen,
        ohne_stufe=ohne_stufe and not seite.stufe_id,
    )
    v.stufen.set(stufen)
    v.kreise.set(kreise)
    eintraege = [Empfang(versand=v, user=absender, name=anzeigename(absender),
                         adresse=zustelladresse(absender), stufe="Probe", reihenfolge=0)]
    for i, (u, stufe) in enumerate(empfaenger(seite, stufen, v.ohne_stufe, ausser=absender,
                                              kreise=kreise), 1):
        adresse = zustelladresse(u)
        eintraege.append(Empfang(
            versand=v, user=u, name=anzeigename(u), adresse=adresse or "", stufe=stufe,
            reihenfolge=i, status=Empfang.Status.OFFEN if adresse else Empfang.Status.OHNE_ADRESSE,
        ))
    if not eintraege[0].adresse:
        eintraege[0].status = Empfang.Status.OHNE_ADRESSE
    Empfang.objects.bulk_create(eintraege)
    return v


# ------------------------------------------------------------------ E-Mail

def _absolut(html, basis):
    return re.sub(r'(href|src)="/', rf'\1="{basis}/', html)


def html_zu_text(html):
    t = re.sub(r"<br\s*/?>", "\n", html or "")
    t = re.sub(r"<li[^>]*>", "\n- ", t)
    t = re.sub(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"\2 (\1)", t, flags=re.S)
    t = re.sub(r"</(p|h[1-6]|ul|ol|blockquote|table|tr)>", "\n\n", t)
    t = htmlmod.unescape(strip_tags(t))
    t = "\n".join(" ".join(z.split()) for z in t.splitlines())
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _anhaenge(versand, seite, user=None):
    """(anzuhängen, nur_als_link) – Bilder gehen nie als Anhang mit.

    Nur Anhänge, die die empfangende Person sehen darf (Kreis des Anhangs)."""
    dateien = ([a for a in seite.anhaenge.all() if not a.ist_bild and rechte.im_kreis(user, a.kreis_id)]
               if seite else [])
    if not versand.mit_anhaengen or not dateien:
        return [], dateien
    try:
        gesamt = sum(a.datei.size for a in dateien)
    except OSError:
        return [], dateien
    if gesamt > settings.FV_NEWSLETTER_MAX_ANHANG_MB * 1024 * 1024:
        return [], dateien
    return dateien, []


def baue_mail(versand, empfang):
    seite = versand.seite
    web = Webseite.aktuell()
    basis = settings.FV_BASIS_URL
    anhaengen, als_link = _anhaenge(versand, seite, empfang.user)
    ctx = {
        "versand": versand, "seite": seite, "web": web, "basis": basis,
        "link": basis + seite.get_absolute_url(),
        "inhalt": _absolut(seite.inhalt, basis) if versand.modus == Versand.Modus.VOLLTEXT else "",
        "inhalt_text": html_zu_text(_absolut(seite.inhalt, basis)),
        "anhaenge_links": [(a, basis + a.get_absolute_url()) for a in als_link],
        "angehaengt": anhaengen,
        "zu_gross": versand.mit_anhaengen and bool(als_link),
        "bilder": bool(seite.bilder()),
        "empfang": empfang, "konto_link": basis + reverse("konto"),
    }
    absender = versand.absender
    profil = getattr(absender, "profil", None) if absender else None
    name = anzeigename(absender) if absender else web.name
    if profil and profil.vereins_email:
        von = konto.mit_name(name, profil.vereins_email)
    else:
        # Fremde Adressen (z. B. gmail.com) dürfen wir nicht als Absender verwenden (SPF/DMARC)
        von = konto.mit_name(f"{name} ({web.name})", konto.absender_adresse())
    antwort = [a for a in [absender.email if absender else "", web.antwort_an] if a]
    if profil and profil.vereins_email:
        antwort[:1] = [profil.vereins_email]
    mail = EmailMultiAlternatives(
        subject=konto.betreff(versand.titel),
        body=render_to_string("newsletter/mail.txt", ctx),
        from_email=von, to=[empfang.adresse],
        reply_to=list(dict.fromkeys(antwort)),
    )
    mail.attach_alternative(render_to_string("newsletter/mail.html", ctx), "text/html")
    for a in anhaengen:
        with a.datei.open("rb") as f:
            mail.attach(a.dateiname, f.read())
    return mail


# ------------------------------------------------------------------ Versanddienst

def schritt(jetzt=None) -> float:
    """Höchstens eine Mail verschicken. Liefert die Wartezeit bis zum nächsten Schritt."""
    jetzt = jetzt or timezone.now()
    v = Versand.objects.filter(status=Versand.Status.LAEUFT).order_by("erstellt", "pk").first()
    if v is None:
        return 5.0
    if v.weiter_ab and v.weiter_ab > jetzt:
        return min(5.0, (v.weiter_ab - jetzt).total_seconds())
    e = v.empfaenge.filter(status=Empfang.Status.OFFEN).order_by("reihenfolge", "pk").first()
    if e is None or v.seite is None:
        if e is not None:   # Seite inzwischen gelöscht
            v.empfaenge.filter(status=Empfang.Status.OFFEN).update(status=Empfang.Status.NICHT_GESENDET)
        Versand.objects.filter(pk=v.pk, status=Versand.Status.LAEUFT).update(
            status=Versand.Status.FERTIG, beendet=jetzt)
        return 0.0
    # Abbruch-Schalter unmittelbar vor dem Senden erneut prüfen
    if not Versand.objects.filter(pk=v.pk, status=Versand.Status.LAEUFT).exists():
        return 0.0
    try:
        baue_mail(v, e).send()
        e.status, e.fehler = Empfang.Status.GESENDET, ""
    except Exception as fehler:   # jede Mail einzeln: ein Fehler stoppt den Versand nicht
        e.status, e.fehler = Empfang.Status.FEHLER, f"{type(fehler).__name__}: {fehler}"[:2000]
    e.zeit = timezone.now()
    e.save(update_fields=["status", "fehler", "zeit"])
    pause = settings.FV_NEWSLETTER_PAUSE if e.reihenfolge == 0 else settings.FV_NEWSLETTER_ABSTAND
    Versand.objects.filter(pk=v.pk).update(weiter_ab=jetzt + timedelta(seconds=pause))
    return 0.0


def herzschlag():
    cache.set(HERZSCHLAG, timezone.now().isoformat(), 120)


def dienst_laeuft():
    return cache.get(HERZSCHLAG) is not None


def abbrechen(versand, user):
    with transaction.atomic():
        n = Versand.objects.filter(pk=versand.pk, status=Versand.Status.LAEUFT).update(
            status=Versand.Status.ABGEBROCHEN, beendet=timezone.now(), abgebrochen_von=user)
        if n:
            versand.empfaenge.filter(status=Empfang.Status.OFFEN).update(
                status=Empfang.Status.NICHT_GESENDET)
    return bool(n)


# ------------------------------------------------------------------ Oberfläche

class VersandForm(forms.Form):
    modus = forms.ChoiceField(label="Inhalt", choices=Versand.Modus.choices,
                              widget=forms.RadioSelect, initial=Versand.Modus.LINK)
    ankuendigung = forms.CharField(
        label="Ankündigung", required=False, widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Kurzer Text, der über der Seite in der E-Mail steht (optional).")
    mit_anhaengen = forms.BooleanField(
        label="Anhänge mitsenden", required=False,
        help_text=f"Bilder nie. Sind die Dateien zusammen größer als "
                  f"{settings.FV_NEWSLETTER_MAX_ANHANG_MB} MB, stehen stattdessen Links in der E-Mail.")
    stufen = forms.ModelMultipleChoiceField(label="An", queryset=Stufe.objects.none(),
                                            widget=forms.CheckboxSelectMultiple, required=False)
    ohne_stufe = forms.BooleanField(label="Konten ohne Stufe", required=False)
    kreise = forms.ModelMultipleChoiceField(
        label="An Kreise", queryset=Kreis.objects.all(), widget=forms.CheckboxSelectMultiple,
        required=False, help_text="Zusätzlich oder statt Stufen. Es erhalten nur Personen die "
                                  "E-Mail, die die Seite sehen dürfen.")

    def __init__(self, seite, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seite = seite
        qs = stufen_fuer(seite)
        self.fields["stufen"].queryset = qs
        self.fields["stufen"].initial = [] if seite.kreis_id else list(qs)
        if seite.kreis_id:
            self.fields["kreise"].initial = [seite.kreis_id]
        if not Kreis.objects.exists():
            del self.fields["kreise"]
        if seite.stufe_id:
            del self.fields["ohne_stufe"]
        if not [a for a in seite.anhaenge.all() if not a.ist_bild]:
            del self.fields["mit_anhaengen"]

    def clean(self):
        daten = super().clean()
        if not daten.get("stufen") and not daten.get("ohne_stufe") and not daten.get("kreise"):
            raise forms.ValidationError("Bitte mindestens eine Stufe oder einen Kreis auswählen.")
        return daten


@nur_vorstand
@require_http_methods(["GET", "POST"])
def neu(request, pk):
    seite = get_object_or_404(Seite.objects.prefetch_related("anhaenge"), pk=pk)
    form = VersandForm(seite, request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        v = versand_anlegen(seite, request.user, modus=d["modus"], ankuendigung=d["ankuendigung"],
                            mit_anhaengen=d.get("mit_anhaengen", False), stufen=list(d["stufen"]),
                            ohne_stufe=d.get("ohne_stufe", False), kreise=list(d.get("kreise") or []))
        messages.success(request, "Der Versand ist gestartet. Zuerst erhalten Sie selbst die E-Mail.")
        return redirect(v)
    vorschau = empfaenger(seite, list(stufen_fuer(seite)), not seite.stufe_id, ausser=request.user,
                          kreise=list(Kreis.objects.all()))
    return render(request, "newsletter/neu.html", {
        "seite": seite, "form": form,
        "anzahl": len(vorschau),
        "ohne_adresse": [(u, s) for u, s in vorschau if not zustelladresse(u)],
        "eigene_adresse": zustelladresse(request.user),
        "pause_min": round(settings.FV_NEWSLETTER_PAUSE / 60, 1),
        "frueher": seite.versaende.select_related("absender")[:20],
    })


@nur_vorstand
def status(request, pk):
    v = get_object_or_404(Versand.objects.select_related("seite", "absender"), pk=pk)
    return render(request, "newsletter/status.html", {
        "v": v, "zaehlung": v.zaehlung(), "empfaenge": v.empfaenge.all(),
        "pause": v.in_pause(), "laeuft": v.status == Versand.Status.LAEUFT,
        "dienst": dienst_laeuft(), "S": Empfang.Status,
    })


@nur_vorstand
@require_POST
def abbrechen_view(request, pk):
    v = get_object_or_404(Versand, pk=pk)
    if abbrechen(v, request.user):
        messages.warning(request, "Der Versand wurde abgebrochen.")
    return redirect(v)


@nur_vorstand
@require_POST
def fortsetzen(request, pk):
    """Pause nach der Probe vorzeitig beenden."""
    v = get_object_or_404(Versand, pk=pk)
    if v.in_pause():
        Versand.objects.filter(pk=v.pk).update(weiter_ab=timezone.now())
        messages.success(request, "Der Versand an alle läuft jetzt.")
    return redirect(v)


@nur_vorstand
def uebersicht(request):
    return render(request, "newsletter/uebersicht.html", {
        "versaende": Versand.objects.select_related("absender", "seite")[:100],
    })
