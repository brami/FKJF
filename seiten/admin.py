"""Vorläufige Bearbeitung über die Django-Verwaltung.

Zugang haben nur Benutzer der Gruppe Vorstand (is_staff + Rechte der Gruppe).
Eine eigene, einfachere Bearbeitungsoberfläche folgt in einem späteren Schritt.
"""

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from . import rechte
from .models import Anhang, Seite


class NurVorstand:
    """Bearbeitungsrechte ausschließlich nach der zentralen Rechteprüfung."""

    def _erlaubt(self, request):
        return request.user.is_staff and rechte.darf_bearbeiten(request.user)

    def has_module_permission(self, request):
        return self._erlaubt(request)

    def has_view_permission(self, request, obj=None):
        return self._erlaubt(request)

    def has_add_permission(self, request, *args):
        return self._erlaubt(request)

    def has_change_permission(self, request, obj=None):
        return self._erlaubt(request)

    def has_delete_permission(self, request, obj=None):
        return self._erlaubt(request)


class AnhangInline(NurVorstand, admin.TabularInline):
    model = Anhang
    extra = 1
    fields = ("datei", "bezeichnung", "dateiname")
    readonly_fields = ("dateiname",)


@admin.register(Seite)
class SeiteAdmin(NurVorstand, SimpleHistoryAdmin):
    list_display = ("titel", "datum", "stufe", "geaendert")
    list_filter = ("stufe",)
    search_fields = ("titel", "inhalt")
    date_hierarchy = "datum"
    inlines = [AnhangInline]
