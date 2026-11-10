import os

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from seiten import views

# Die Verwaltung liegt nicht unter /admin/, um automatisierte Angriffe zu erschweren.
ADMIN_PFAD = os.environ.get("FV_ADMIN_PFAD", "verwaltung/")

admin.site.site_header = "Förderverein KF/JF Kreuzau – Verwaltung"
admin.site.site_title = "Verwaltung"
admin.site.index_title = "Übersicht"

urlpatterns = [
    path("", views.startseite, name="startseite"),
    path("seite/<int:pk>/", views.seite, name="seite"),
    path("anhang/<int:pk>/", views.anhang, name="anhang"),
    path("anmelden/", auth_views.LoginView.as_view(), name="login"),
    path("abmelden/", auth_views.LogoutView.as_view(), name="logout"),
    path(ADMIN_PFAD, admin.site.urls),
]
