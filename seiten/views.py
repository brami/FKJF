from django.contrib.auth.views import redirect_to_login
from django.db import connection
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from . import rechte
from .models import Anhang, Seite


def _verweigert(request):
    """Nicht angemeldet: zur Anmeldung. Angemeldet ohne Recht: 404.

    Ein 404 statt 403 verrät nicht, dass es eine geschützte Seite gibt.
    """
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    raise Http404


@require_GET
def startseite(request):
    seiten = rechte.sichtbare_seiten(request.user).prefetch_related("anhaenge")
    return render(request, "seiten/startseite.html", {
        "seiten": seiten,
        "darf_bearbeiten": rechte.darf_bearbeiten(request.user),
    })


@require_GET
def seite(request, pk):
    s = get_object_or_404(Seite, pk=pk)
    if not rechte.darf_lesen(request.user, s):
        return _verweigert(request)
    return render(request, "seiten/seite.html", {
        "seite": s,
        "anhaenge": s.anhaenge.all(),
        "darf_bearbeiten": rechte.darf_bearbeiten(request.user),
    })


def _ausliefern(request, pk, feld):
    a = get_object_or_404(Anhang.objects.select_related("seite"), pk=pk)
    if not rechte.darf_lesen(request.user, a.seite):
        return _verweigert(request)
    datei = getattr(a, feld)
    if not datei:
        raise Http404
    try:
        fh = datei.open("rb")
    except FileNotFoundError:
        raise Http404
    if a.ist_bild:
        # Bilder im Browser anzeigen; zwischenspeichern nur im eigenen Browser
        antwort = FileResponse(fh, as_attachment=False, filename=a.dateiname)
        antwort["Cache-Control"] = "private, max-age=3600"
    else:
        antwort = FileResponse(fh, as_attachment=True, filename=a.dateiname)
        antwort["Cache-Control"] = "private, no-store"
    return antwort


@require_GET
def anhang(request, pk):
    return _ausliefern(request, pk, "datei")


@require_GET
def anhang_variante(request, pk, variante):
    feld = {"bild": "bild", "vorschau": "vorschaubild"}.get(variante)
    if feld is None:
        raise Http404
    return _ausliefern(request, pk, feld)


@require_GET
def gesund(request):
    """Statusprüfung für Installation und Überwachung: Anwendung und Datenbank laufen."""
    with connection.cursor() as c:
        c.execute("SELECT 1")
    antwort = HttpResponse("ok", content_type="text/plain")
    antwort["Cache-Control"] = "no-store"
    return antwort
