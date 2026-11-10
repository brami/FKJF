from django import forms
from django.forms import inlineformset_factory

from .models import Anhang, Seite


class SeiteForm(forms.ModelForm):
    class Meta:
        model = Seite
        fields = ["titel", "datum", "stufe", "inhalt"]
        widgets = {
            "datum": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "inhalt": forms.Textarea(attrs={"rows": 20, "data-editor": "tinymce"}),
        }
        labels = {"titel": "Titel", "datum": "Datum", "inhalt": "Inhalt"}


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
        label="Dateien hinzufügen", required=False,
        help_text="Mehrere Dateien auf einmal möglich, je Datei höchstens 20 MB.",
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


AnhangFormSet = inlineformset_factory(
    Seite, Anhang, fields=["bezeichnung"], extra=0, can_delete=True,
    labels={"bezeichnung": "Bezeichnung"},
)
