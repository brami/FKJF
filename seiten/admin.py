"""Django-Verwaltung: Benutzer pflegen und einladen, Seiten (zusätzlich zur
eigenen Bearbeitungsoberfläche).

Zugang haben nur Benutzer der Gruppe Vorstand (und Administratoren). Die
Anmeldung läuft immer über die normale Anmeldeseite, damit die
Zwei-Faktor-Anmeldung nicht umgangen werden kann.
"""

from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.utils.html import format_html
from simple_history.admin import SimpleHistoryAdmin

from . import rechte
from .konto import mails_werden_verschickt, sende_einladung
from .models import Anhang, Seite
from .stufen import GRUPPE_ZU_STUFE

User = get_user_model()


class NurVorstand:
    """Bearbeitungsrechte ausschließlich nach der zentralen Rechteprüfung."""

    def _erlaubt(self, request):
        return rechte.darf_bearbeiten(request.user)

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
    fields = ("datei", "bezeichnung", "titelbild", "dateiname")
    readonly_fields = ("dateiname",)


@admin.register(Seite)
class SeiteAdmin(NurVorstand, SimpleHistoryAdmin):
    list_display = ("titel", "datum", "stufe", "geaendert")
    list_filter = ("stufe",)
    search_fields = ("titel", "inhalt")
    date_hierarchy = "datum"
    inlines = [AnhangInline]


# ------------------------------------------------------------------ Benutzer

class EindeutigeEmail:
    """Jede E-Mail-Adresse nur einmal (Anmeldung auch mit der Adresse möglich)."""

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip()
        andere = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            andere = andere.exclude(pk=self.instance.pk)
        if email and andere.exists():
            raise forms.ValidationError("Diese E-Mail-Adresse gehört bereits zu einem anderen Konto.")
        return email


class BenutzerAnlegenForm(EindeutigeEmail, forms.ModelForm):
    einladen = forms.BooleanField(
        label="Einladung sofort per E-Mail senden", required=False, initial=True,
        help_text="Die Person setzt ihr Passwort über den Link selbst (7 Tage gültig).",
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "groups"]
        widgets = {"groups": forms.CheckboxSelectMultiple}
        help_texts = {
            "username": "Zur Anmeldung, z. B. vorname.nachname. Anmelden geht auch mit der E-Mail-Adresse.",
            "groups": "Die höchste Gruppe bestimmt, was die Person sehen darf.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.fields["groups"].queryset = Group.objects.filter(name__in=GRUPPE_ZU_STUFE)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_unusable_password()
        if commit:
            user.save()
            self.save_m2m()
        return user


class BenutzerAendernForm(EindeutigeEmail, forms.ModelForm):
    class Meta:
        model = User
        fields = "__all__"
        widgets = {"groups": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "groups" in self.fields:
            self.fields["groups"].queryset = Group.objects.filter(name__in=GRUPPE_ZU_STUFE)
        if "email" in self.fields:
            self.fields["email"].required = True


@admin.display(description="Gruppen")
def gruppen(user):
    return ", ".join(g.name for g in user.groups.all()) or "–"


admin.site.unregister(User)
admin.site.unregister(Group)  # die Gruppen sind fest vorgegeben (Migration)


@admin.register(User)
class BenutzerAdmin(NurVorstand, UserAdmin):
    add_form = BenutzerAnlegenForm
    form = BenutzerAendernForm
    add_fieldsets = ((None, {"fields": ("username", "first_name", "last_name", "email",
                                        "groups", "einladen")}),)
    list_display = ("username", "first_name", "last_name", "email", gruppen, "is_active", "last_login")
    list_filter = ("groups", "is_active")
    search_fields = ("username", "first_name", "last_name", "email")
    ordering = ("last_name", "first_name", "username")
    readonly_fields = ("last_login", "date_joined")
    actions = ["einladung_senden"]

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets
        felder = [
            (None, {"fields": ("username",)}),
            ("Person", {"fields": ("first_name", "last_name", "email")}),
            ("Zugang", {"fields": ("is_active", "groups"),
                        "description": "Deaktivierte Konten können sich nicht anmelden "
                                       "und erhalten keine Newsletter."}),
            ("Zeiten", {"fields": ("last_login", "date_joined")}),
        ]
        if request.user.is_superuser:
            felder.insert(3, ("Administrator", {"fields": ("password", "is_staff", "is_superuser")}))
        return felder

    def get_queryset(self, request):
        qs = super().get_queryset(request).prefetch_related("groups")
        # Der Vorstand sieht und ändert keine Administratorkonten
        return qs if request.user.is_superuser else qs.filter(is_superuser=False)

    def _darf_konto(self, request, obj):
        return obj is None or request.user.is_superuser or not obj.is_superuser

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and self._darf_konto(request, obj)

    def has_delete_permission(self, request, obj=None):
        return (super().has_delete_permission(request, obj) and self._darf_konto(request, obj)
                and obj != request.user)

    def user_change_password(self, request, id, form_url=""):
        # Passwörter setzen die Personen selbst (Einladung / Passwort vergessen)
        if not request.user.is_superuser:
            raise PermissionDenied
        return super().user_change_password(request, id, form_url)

    def _einladen(self, request, user):
        if not user.email:
            self.message_user(request, f"{user}: keine E-Mail-Adresse – keine Einladung.", messages.WARNING)
            return
        link = sende_einladung(user)
        if mails_werden_verschickt():
            self.message_user(request, f"Einladung an {user.email} gesendet.", messages.SUCCESS)
        else:
            self.message_user(request, format_html(
                "Der Mailversand ist noch nicht eingerichtet. Bitte den Link für {} selbst "
                "weitergeben (7 Tage gültig, nur einmal verwendbar):<br><code>{}</code>",
                user, link), messages.WARNING)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if not change and form.cleaned_data.get("einladen"):
            self._einladen(request, form.instance)

    @admin.action(description="Einladung (erneut) senden")
    def einladung_senden(self, request, queryset):
        for user in queryset:
            self._einladen(request, user)
