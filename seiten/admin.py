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
from . import mail
from .models import AdressSperre, Alias, Anhang, Profil, Seite, Stufe, Verteiler, Webseite

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
        vereinsadressen = Profil.objects.filter(vereins_email__iexact=email)
        if self.instance.pk:
            andere = andere.exclude(pk=self.instance.pk)
        if email and (andere.exists() or vereinsadressen.exists()):
            raise forms.ValidationError("Diese E-Mail-Adresse gehört bereits zu einem anderen Konto.")
        mail.extern_pruefen(email)
        return email


class ProfilForm(forms.ModelForm):
    class Meta:
        model = Profil
        fields = ["vereins_email", "zustellung"]

    def clean_vereins_email(self):
        adresse = (self.cleaned_data.get("vereins_email") or "").strip().lower() or None
        if adresse and User.objects.filter(email__iexact=adresse).exists():
            raise forms.ValidationError(
                "Diese Adresse ist bereits als externe Adresse eingetragen. Die Vereinsadresse "
                "muss sich von allen externen Adressen unterscheiden.")
        if adresse:
            user = self.instance.user if self.instance.user_id else None
            mail.adresse_pruefen(adresse, user=user, vereinsadresse=True)
        return adresse


class ProfilInline(admin.StackedInline):
    model = Profil
    form = ProfilForm
    can_delete = False
    max_num = 1
    verbose_name = "Postfach und Vereinsmails"
    verbose_name_plural = "Postfach und Vereinsmails"
    fields = ("vereins_email", "zustellung", "postfach_hinweis")
    readonly_fields = ("postfach_hinweis",)

    @admin.display(description="Postfach")
    def postfach_hinweis(self, obj):
        if obj is None or not obj.pk or not obj.hat_postfach:
            return "–"
        if obj.postfach_gesperrt_seit:
            return format_html("gesperrt seit {} – wird am {} gelöscht. Konto aktivieren und "
                               "Vereinsadresse eintragen, um es zu behalten.",
                               obj.postfach_gesperrt_seit.strftime("%d.%m.%Y"),
                               mail.loeschdatum(obj).strftime("%d.%m.%Y"))
        return "vorhanden. Ändern Sie die Vereinsadresse, wird die bisherige automatisch zum Alias."

    def has_view_permission(self, request, obj=None):
        return rechte.darf_bearbeiten(request.user)

    has_add_permission = has_change_permission = has_view_permission


class AliasForm(forms.ModelForm):
    class Meta:
        model = Alias
        fields = ["adresse"]

    def clean_adresse(self):
        user = self.instance.user if self.instance.user_id else None
        return mail.adresse_pruefen(self.cleaned_data.get("adresse"), user=user, alias=self.instance)


class AliasInline(NurVorstand, admin.TabularInline):
    model = Alias
    form = AliasForm
    extra = 0
    fields = ("adresse", "art", "angelegt")
    readonly_fields = ("art", "angelegt")
    verbose_name = "Alias-Adresse"
    verbose_name_plural = "Alias-Adressen (kommen im selben Postfach an)"


STUFE_HILFE = ("Die höchste Stufe bestimmt, was die Person sieht und ob sie Seiten bearbeiten darf. "
               "Meist genügt eine.")


class StufenFilter(admin.SimpleListFilter):
    title = "Stufe"
    parameter_name = "stufe"

    def lookups(self, request, model_admin):
        return [(str(s.gruppe_id), s.name) for s in Stufe.objects.order_by("rang")] + [("ohne", "ohne Stufe")]

    def queryset(self, request, queryset):
        if self.value() == "ohne":
            return queryset.exclude(groups__stufe__isnull=False)
        if self.value():
            return queryset.filter(groups=self.value())
        return queryset


class BenutzerAnlegenForm(EindeutigeEmail, forms.ModelForm):
    einladen = forms.BooleanField(
        label="Einladung sofort per E-Mail senden", required=False, initial=True,
        help_text="Die Person setzt ihr Passwort über den Link selbst (7 Tage gültig).",
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "groups"]
        widgets = {"groups": forms.CheckboxSelectMultiple}
        labels = {"groups": "Stufe"}
        help_texts = {
            "username": "Zur Anmeldung, z. B. vorname.nachname. Anmelden geht auch mit der E-Mail-Adresse.",
            "groups": STUFE_HILFE,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.fields["groups"].queryset = Group.objects.filter(stufe__isnull=False).order_by("stufe__rang")

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
        labels = {"groups": "Stufe", "is_active": "Aktiv"}
        help_texts = {"groups": STUFE_HILFE,
                      "is_active": "Statt ausgeschiedene Personen zu löschen, hier den Haken entfernen."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "groups" in self.fields:
            self.fields["groups"].queryset = Group.objects.filter(stufe__isnull=False).order_by("stufe__rang")
        if "email" in self.fields:
            self.fields["email"].required = True


@admin.display(description="Stufe")
def gruppen(user):
    return ", ".join(g.name for g in user.groups.all()) or "–"


admin.site.unregister(User)
admin.site.unregister(Group)  # Gruppen entstehen automatisch zu jeder Stufe


@admin.register(User)
class BenutzerAdmin(NurVorstand, UserAdmin):
    inlines = [ProfilInline, AliasInline]

    def get_inlines(self, request, obj):
        # Aliase erst nach dem Anlegen (sie brauchen die Vereinsadresse)
        return self.inlines if obj is not None else [ProfilInline]
    add_form = BenutzerAnlegenForm
    form = BenutzerAendernForm
    add_fieldsets = ((None, {"fields": ("username", "first_name", "last_name", "email",
                                        "groups", "einladen")}),)
    list_display = ("username", "first_name", "last_name", "email", "vereinsadresse", gruppen,
                    "is_active", "last_login")
    list_filter = (StufenFilter, "is_active")
    search_fields = ("username", "first_name", "last_name", "email")
    ordering = ("last_name", "first_name", "username")
    readonly_fields = ("last_login", "date_joined")
    actions = ["einladung_senden"]

    @admin.display(description="Vereinsadresse")
    def vereinsadresse(self, user):
        profil = getattr(user, "profil", None)
        return (profil.vereins_email if profil else None) or "–"

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets
        felder = [
            (None, {"fields": ("username",)}),
            ("Person", {"fields": ("first_name", "last_name", "email"),
                        "description": "E-Mail-Adresse = externe Adresse: für „Passwort vergessen“, "
                                       "Einladungen und – je nach Einstellung – Vereinsmails."}),
            ("Zugang", {"fields": ("is_active", "groups"),
                        "description": "Deaktivierte Konten können sich nicht anmelden "
                                       "und erhalten keine Newsletter."}),
            ("Zeiten", {"fields": ("last_login", "date_joined")}),
        ]
        if request.user.is_superuser:
            felder.insert(3, ("Administrator", {"fields": ("password", "is_staff", "is_superuser")}))
        return felder

    def get_queryset(self, request):
        qs = super().get_queryset(request).prefetch_related("groups").select_related("profil")
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
            self.message_user(request, f"Keine E-Mail-Adresse für {user} – keine Einladung gesendet.",
                              messages.WARNING)
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


@admin.register(Stufe)
class StufeAdmin(admin.ModelAdmin):
    """Stufen anlegen, umbenennen, ordnen – nur für Administratoren.

    Eine Stufe lässt sich nur löschen, solange ihr keine Seite zugeordnet ist.
    """

    list_display = ("name", "rang", "darf_bearbeiten", "anzahl_seiten", "anzahl_personen")
    list_editable = ("rang",)
    ordering = ("rang",)

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    has_view_permission = has_add_permission = has_change_permission = has_delete_permission = (
        lambda self, request, obj=None: request.user.is_active and request.user.is_superuser
    )

    @admin.display(description="Seiten")
    def anzahl_seiten(self, obj):
        return obj.seiten.count()

    @admin.display(description="Personen")
    def anzahl_personen(self, obj):
        return obj.gruppe.user_set.count()


@admin.register(Webseite)
class WebseiteAdmin(admin.ModelAdmin):
    """Name und feste Texte der Webseite – genau ein Eintrag, nur für Administratoren."""

    def _admin(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_module_permission(self, request):
        return self._admin(request)

    def has_view_permission(self, request, obj=None):
        return self._admin(request)

    def has_change_permission(self, request, obj=None):
        return self._admin(request)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Keine Liste: direkt zum einzigen Eintrag
        from django.shortcuts import redirect
        if not self._admin(request):
            raise PermissionDenied
        return redirect("admin:seiten_webseite_change", Webseite.aktuell().pk)


# ----------------------------------------------------------------- Mail

class VerteilerForm(forms.ModelForm):
    class Meta:
        model = Verteiler
        fields = ["adresse", "beschreibung", "stufen", "personen", "weitere_adressen", "offen", "aktiv",
                  "archiv", "archiv_tage"]
        widgets = {"stufen": forms.CheckboxSelectMultiple,
                   "weitere_adressen": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["personen"].queryset = User.objects.filter(is_active=True).order_by(
            "last_name", "first_name", "username")

    def clean_adresse(self):
        return mail.adresse_pruefen(self.cleaned_data.get("adresse"), verteiler=self.instance)

    def clean_weitere_adressen(self):
        zeilen = [z.strip().lower() for z in (self.cleaned_data.get("weitere_adressen") or "").split()]
        for z in zeilen:
            try:
                forms.EmailField().clean(z)
            except forms.ValidationError:
                raise forms.ValidationError(f"„{z}“ ist keine gültige E-Mail-Adresse.")
        return "\n".join(dict.fromkeys(zeilen))


@admin.register(Verteiler)
class VerteilerAdmin(NurVorstand, admin.ModelAdmin):
    form = VerteilerForm
    list_display = ("adresse", "beschreibung", "empfaenger_text", "offen", "archiv", "aktiv")
    list_filter = ("aktiv", "offen", "archiv")
    search_fields = ("adresse", "beschreibung")
    filter_horizontal = ("personen",)
    readonly_fields = ("empfaenger_jetzt", "archiv_lesen")

    @admin.display(description="Archiv lesen dürfen zurzeit")
    def archiv_lesen(self, obj):
        if not obj.pk or not obj.archiv:
            return "–"
        return ", ".join(mail.archiv_leser(obj)) or "niemand (keine Empfänger mit Postfach)"

    @admin.display(description="Empfänger")
    def empfaenger_text(self, obj):
        return len(mail.verteiler_empfaenger(obj))

    @admin.display(description="Empfänger zurzeit")
    def empfaenger_jetzt(self, obj):
        if not obj.pk:
            return "–"
        return ", ".join(mail.verteiler_empfaenger(obj)) or "niemand"


@admin.register(AdressSperre)
class AdressSperreAdmin(NurVorstand, admin.ModelAdmin):
    """Frei gewordene Adressen. Der Vorstand kann eine Sperre vorzeitig aufheben (löschen)."""

    list_display = ("adresse", "frei_ab", "user", "grund")
    search_fields = ("adresse",)
    fields = ("adresse", "frei_ab", "user", "grund")
    readonly_fields = ("adresse", "user", "grund")

    def has_add_permission(self, request, *args):
        return False
