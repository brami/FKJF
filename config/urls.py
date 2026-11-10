import os

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from seiten import bearbeiten, views

# Die Verwaltung liegt nicht unter /admin/, um automatisierte Angriffe zu erschweren.
ADMIN_PFAD = os.environ.get("FV_ADMIN_PFAD", "verwaltung/")

admin.site.site_header = "Förderverein KF/JF Kreuzau – Verwaltung"
admin.site.site_title = "Verwaltung"
admin.site.index_title = "Übersicht"

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
    path("anmelden/", auth_views.LoginView.as_view(), name="login"),
    path("abmelden/", auth_views.LogoutView.as_view(), name="logout"),
    path(ADMIN_PFAD, admin.site.urls),
]
