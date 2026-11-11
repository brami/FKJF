"""Bearbeitungsoberfläche für den Vorstand: Seiten anlegen, ändern, löschen,
Anhänge verwalten, Versionsverlauf ansehen und alte Fassungen wiederherstellen.
"""

import difflib
import html
import re
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import formats, timezone
from django.utils.csp import CSP
from django.utils.html import strip_tags
from django.views.decorators.csp import csp_override
from django.views.decorators.http import require_http_methods, require_POST

from . import rechte
from .forms import AnhangFormSet, NeueAnhaengeForm, SeiteForm
from .models import Seite, Stufe
from .stufen import OEFFENTLICH

# Der Editor setzt Stilangaben direkt an seinen Bedienelementen. Das wird nur auf
# den Bearbeitungsseiten erlaubt; Skripte bleiben auf eigene Dateien beschränkt.
EDITOR_CSP = {
    **settings.SECURE_CSP,
    "style-src": [CSP.SELF, CSP.UNSAFE_INLINE],
}


def nur_vorstand(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not rechte.darf_bearbeiten(request.user):
            raise Http404
        return view(request, *args, **kwargs)
    return wrapper


def _speichern(request, seite, form, anhang_formset, neue):
    with transaction.atomic():
        seite = form.save()
        anhang_formset.instance = seite
        anhang_formset.save()
        for a in neue.anhaenge:
            a.seite = seite
            a.save()
    return seite


@nur_vorstand
@csp_override(EDITOR_CSP)
@require_http_methods(["GET", "POST"])
def seite_bearbeiten(request, pk=None):
    seite = get_object_or_404(Seite, pk=pk) if pk else Seite()
    if request.method == "POST":
        form = SeiteForm(request.POST, instance=seite)
        anhang_formset = AnhangFormSet(request.POST, instance=seite, prefix="anhang")
        neue = NeueAnhaengeForm(request.POST, request.FILES, seite=seite)
        if form.is_valid() and anhang_formset.is_valid() and neue.is_valid():
            seite = _speichern(request, seite, form, anhang_formset, neue)
            messages.success(request, "Die Seite wurde gespeichert.")
            return redirect(seite)
    else:
        form = SeiteForm(instance=seite)
        anhang_formset = AnhangFormSet(instance=seite, prefix="anhang")
        neue = NeueAnhaengeForm(seite=seite)
    return render(request, "seiten/bearbeiten.html", {
        "seite": seite, "form": form, "anhang_formset": anhang_formset, "neue": neue,
    })


@nur_vorstand
@require_http_methods(["GET", "POST"])
def seite_loeschen(request, pk):
    seite = get_object_or_404(Seite, pk=pk)
    if request.method == "POST":
        titel = seite.titel
        seite.delete()
        messages.success(request, f"Die Seite „{titel}“ wurde gelöscht.")
        return redirect("startseite")
    return render(request, "seiten/loeschen.html", {"seite": seite})


@nur_vorstand
def verlauf(request, pk):
    seite = get_object_or_404(Seite, pk=pk)
    fassungen = seite.history.select_related("history_user").order_by("-history_date", "-history_id")
    return render(request, "seiten/verlauf.html", {"seite": seite, "fassungen": fassungen})


_BLOCKENDE = re.compile(r"</(p|h[1-6]|li|tr|blockquote)>|<br\s*/?>|<hr\s*/?>", re.I)


def _textzeilen(html_text):
    text = html.unescape(strip_tags(_BLOCKENDE.sub("\n", html_text or "")))
    return [z.strip() for z in text.splitlines() if z.strip()]


def _stufen_name(stufe_id):
    if not stufe_id:
        return OEFFENTLICH
    stufe = Stufe.objects.filter(pk=stufe_id).first()
    return stufe.name if stufe else "(gelöschte Stufe)"


@nur_vorstand
def fassung(request, pk, history_id):
    seite = get_object_or_404(Seite, pk=pk)
    alt = get_object_or_404(seite.history, history_id=history_id)
    datum = formats.date_format(timezone.localtime(alt.history_date), "DATETIME_FORMAT")
    unterschiede = difflib.HtmlDiff(wrapcolumn=38).make_table(
        _textzeilen(alt.inhalt), _textzeilen(seite.inhalt),
        f"Fassung vom {datum}", "Aktuelle Fassung", context=True, numlines=2,
    )
    felder = []
    if alt.titel != seite.titel:
        felder.append(("Titel", alt.titel, seite.titel))
    if alt.datum != seite.datum:
        felder.append(("Datum", alt.datum, seite.datum))
    if alt.stufe_id != seite.stufe_id:
        felder.append(("Sichtbar für", _stufen_name(alt.stufe_id), seite.stufe_name))
    return render(request, "seiten/fassung.html", {
        "seite": seite, "alt": alt, "datum": datum,
        "unterschiede": unterschiede, "felder": felder,
        "gleich_inhalt": _textzeilen(alt.inhalt) == _textzeilen(seite.inhalt),
    })


@nur_vorstand
@require_POST
def wiederherstellen(request, pk, history_id):
    seite = get_object_or_404(Seite, pk=pk)
    alt = get_object_or_404(seite.history, history_id=history_id)
    for feld in ("titel", "datum", "stufe_id", "inhalt"):
        setattr(seite, feld, getattr(alt, feld))
    if seite.stufe_id and not Stufe.objects.filter(pk=seite.stufe_id).exists():
        messages.error(request, "Die Stufe dieser Fassung gibt es nicht mehr. "
                                "Bitte die Seite bearbeiten und eine Stufe wählen.")
        return redirect("seite_verlauf", pk=seite.pk)
    datum = formats.date_format(timezone.localtime(alt.history_date), "DATETIME_FORMAT")
    seite._change_reason = f"Wiederhergestellt aus der Fassung vom {datum}"
    seite.save()
    messages.success(request, f"Die Fassung vom {datum} wurde wiederhergestellt.")
    return redirect(seite)
