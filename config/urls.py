import os

from django.contrib import admin
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect
from django.urls import include, path, reverse
from django.views.generic import RedirectView

from seiten import bearbeiten, konto, rechte, views

# Die Verwaltung liegt nicht unter /admin/, um automatisierte Angriffe zu erschweren.
ADMIN_PFAD = os.environ.get("FV_ADMIN_PFAD", "verwaltung/")

admin.site.site_header = "Förderverein KF/JF Kreuzau – Verwaltung"
admin.site.site_title = "Verwaltung"
admin.site.index_title = "Übersicht"
# Zugang zur Verwaltung nur für den Vorstand – Anmeldung immer über die normale
# Anmeldeseite (sonst ließe sich die Zwei-Faktor-Anmeldung umgehen)
admin.site.has_permission = lambda request: rechte.darf_bearbeiten(request.user)
admin.site.login = lambda request, extra_context=None: redirect_to_login(
    request.GET.get("next") or reverse("admin:index"))
admin.site.password_change = lambda request, extra_context=None: redirect("account_change_password")

urlpatterns = [
    path("", views.startseite, name="startseite"),
    path("seite/<int:pk>/", views.seite, name="seite"),
    path("anhang/<int:pk>/", views.anhang, name="anhang"),
    path("seite/neu/", bearbeiten.seite_bearbeiten, name="seite_neu"),
    path("seite/<int:pk>/bearbeiten/", bearbeiten.seite_bearbeiten, name="seite_bearbeiten"),
    path("seite/<int:pk>/loeschen/", bearbeiten.seite_loeschen, name="seite_loeschen"),
    path("seite/<int:pk>/verlauf/", bearbeiten.verlauf, name="seite_verlauf"),
    path("seite/<int:pk>/verlauf/<int:history_id>/", bearbeiten.fassung, name="seite_fassung"),
    path("seite/<int:pk>/verlauf/<int:history_id>/wiederherstellen/",
         bearbeiten.wiederherstellen, name="seite_wiederherstellen"),
    path("konto/", konto.konto, name="konto"),
    # E-Mail-Adressen pflegt der Vorstand; Registrierung gibt es nicht
    path("konto/email/", RedirectView.as_view(pattern_name="konto")),
    path("konto/", include("allauth.urls")),
    path("anmelden/", RedirectView.as_view(pattern_name="account_login", query_string=True)),
    path("gesund/", views.gesund, name="gesund"),
    path(ADMIN_PFAD, admin.site.urls),
]
