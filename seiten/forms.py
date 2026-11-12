from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from .models import Anhang, Seite, Stufe
from .stufen import OEFFENTLICH


class SeiteForm(forms.ModelForm):
    class Meta:
        model = Seite
        fields = ["titel", "datum", "stufe", "kreis", "inhalt"]
        widgets = {
            "datum": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "inhalt": forms.Textarea(attrs={"rows": 20, "data-editor": "tinymce"}),
        }
        labels = {"titel": "Titel", "datum": "Datum", "inhalt": "Inhalt"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        feld = self.fields["stufe"]
        feld.queryset = Stufe.objects.order_by("rang")
        feld.empty_label = f"{OEFFENTLICH} (ohne Anmeldung)"
        if not self.instance.pk and not self.is_bound and not self.initial.get("stufe"):
            self.initial["stufe"] = Stufe.voreinstellung()
        self.fields["kreis"].empty_label = "– kein Kreis –"


class MehrereDateienWidget(forms.ClearableFileInput):
    allow_multiple_selected = True


class MehrereDateienFeld(forms.FileField):
    widget = MehrereDateienWidget

    def clean(self, data, initial=None):
        einzeln = super().clean
        if isinstance(data, (list, tuple)):
            return [einzeln(d, initial) for d in data]
        return [einzeln(data, initial)] if data else []


class NeueAnhaengeForm(forms.Form):
    dateien = MehrereDateienFeld(
        label="Dateien und Bilder hinzufügen", required=False,
        help_text="Mehrere auf einmal möglich, je Datei höchstens 20 MB. Bilder (JPG, PNG, WebP) "
                  "erscheinen auf der Seite: das erste bzw. ausgewählte als Titelbild, weitere "
                  "als Galerie. Standortdaten in Fotos werden automatisch entfernt.",
    )

    def __init__(self, *args, seite=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.seite = seite
        self.anhaenge = []

    def clean_dateien(self):
        """Prüft jede Datei mit den Validatoren des Modells (Endung, Größe)."""
        dateien = self.cleaned_data.get("dateien") or []
        fehler = []
        self.anhaenge = []
        for d in dateien:
            a = Anhang(seite=self.seite, datei=d)
            try:
                a.full_clean(exclude=["seite", "dateiname"])
            except forms.ValidationError as e:
                fehler += [f"{d.name}: {m}" for m in e.messages]
            self.anhaenge.append(a)
        if fehler:
            raise forms.ValidationError(fehler)
        return dateien


class AnhangForm(forms.ModelForm):
    class Meta:
        model = Anhang
        fields = ["bezeichnung", "titelbild", "kreis"]
        labels = {"bezeichnung": "Bezeichnung / Bildunterschrift", "kreis": "Nur für Kreis"}

    def clean_titelbild(self):
        # Nur Bilder können Titelbild sein
        return self.cleaned_data.get("titelbild") and self.instance.ist_bild


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kreis"].empty_label = "alle, die die Seite sehen"


class BaseAnhangFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        gewaehlt = [f for f in self.forms
                    if f.cleaned_data.get("titelbild") and not f.cleaned_data.get("DELETE")]
        if len(gewaehlt) > 1:
            raise forms.ValidationError("Bitte nur ein Bild als Titelbild auswählen.")


AnhangFormSet = inlineformset_factory(
    Seite, Anhang, form=AnhangForm, formset=BaseAnhangFormSet, extra=0, can_delete=True,
)
