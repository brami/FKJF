from django.db import connection
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from . import rechte
from .models import Anhang, Seite


def _verweigert(request):
    """Ohne Leserecht: immer 404 – wie bei einer Seite, die es nicht gibt.

    So verrät die Webseite nicht, dass unter der Adresse eine geschützte Seite liegt.
    Die Fehlerseite (404.html) bietet Nicht-Angemeldeten die Anmeldung an und führt
    danach zur gewünschten Adresse zurück.
    """
    raise Http404


@require_GET
def startseite(request):
    seiten = rechte.sichtbare_seiten(request.user).select_related("kreis").prefetch_related("anhaenge")
    return render(request, "seiten/startseite.html", {
        "seiten": rechte.anhaenge_zuordnen(request.user, list(seiten)),
        "darf_bearbeiten": rechte.darf_bearbeiten(request.user),
    })


@require_GET
def seite(request, pk):
    s = get_object_or_404(Seite.objects.select_related("kreis").prefetch_related("anhaenge__kreis"), pk=pk)
    if not rechte.darf_lesen(request.user, s):
        return _verweigert(request)
    rechte.anhaenge_zuordnen(request.user, [s])
    return render(request, "seiten/seite.html", {
        "seite": s,
        "anhaenge": s.sichtbare_anhaenge(),
        "darf_bearbeiten": rechte.darf_bearbeiten(request.user),
    })


def _ausliefern(request, pk, feld):
    a = get_object_or_404(Anhang.objects.select_related("seite"), pk=pk)
    if not rechte.darf_anhang(request.user, a):
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


def csrf_fehler(request, reason=""):
    """Formular abgelaufen o. Ä. (CSRF) – verständlich statt Django-Technikseite."""
    return render(request, "403_csrf.html", status=403)


@require_GET
def ueber(request):
    """Über diese Webseite: Software, Urheber, Lizenz, Quellcode (AGPL § 5 d, § 13)."""
    from django.conf import settings
    return render(request, "seiten/ueber.html", {"quellcode": settings.FV_QUELLCODE_URL})


@require_GET
def lizenztext(request, teil="programm"):
    """Volltext der Lizenzen aus dem installierten Programm (LICENSE, docs/LICENSE)."""
    from django.conf import settings
    datei = settings.BASE_DIR / ("LICENSE" if teil == "programm" else "docs/LICENSE")
    if not datei.exists():
        raise Http404
    return HttpResponse(datei.read_text(encoding="utf-8"), content_type="text/plain; charset=utf-8")
