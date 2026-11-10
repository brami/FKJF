from django.contrib.auth.views import redirect_to_login
from django.http import FileResponse, Http404
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
    return render(request, "seiten/startseite.html", {"seiten": seiten})


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


@require_GET
def anhang(request, pk):
    a = get_object_or_404(Anhang.objects.select_related("seite"), pk=pk)
    if not rechte.darf_lesen(request.user, a.seite):
        return _verweigert(request)
    try:
        datei = a.datei.open("rb")
    except FileNotFoundError:
        raise Http404
    antwort = FileResponse(datei, as_attachment=True, filename=a.dateiname)
    antwort["Cache-Control"] = "private, no-store"
    return antwort
