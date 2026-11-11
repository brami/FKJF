import pytest
from django.urls import reverse

from seiten.models import Seite, bereinige_html
from seiten.stufen import Stufe

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("roh,verboten", [
    ('<p>Hallo<script>alert(1)</script></p>', "<script"),
    ('<img src=x onerror="alert(1)">', "onerror"),
    ('<a href="javascript:alert(1)">x</a>', "javascript:"),
    ('<p style="color:red" onclick="x()">x</p>', "onclick"),
    ('<iframe src="https://example.org"></iframe>', "<iframe"),
])
def test_html_wird_bereinigt(roh, verboten):
    assert verboten not in bereinige_html(roh)


def test_erlaubtes_html_bleibt():
    html = '<h2>Tagesordnung</h2><ol><li><strong>Bericht</strong></li></ol>'
    assert bereinige_html(html) == html


def test_seite_speichert_bereinigt():
    s = Seite.objects.create(titel="x", stufe=Stufe.OEFFENTLICH,
                             inhalt="<p>ok</p><script>alert(1)</script>")
    s.refresh_from_db()
    assert "<script" not in s.inhalt


def test_versionsverlauf_wird_gefuehrt():
    s = Seite.objects.create(titel="Einladung", stufe=Stufe.MITGLIEDER, inhalt="<p>1</p>")
    s.inhalt = "<p>2</p>"
    s.save()
    assert s.history.count() == 2
    assert s.history.earliest().inhalt == "<p>1</p>"


def test_csp_kopfzeile(client):
    r = client.get(reverse("startseite"))
    assert "default-src 'self'" in r["Content-Security-Policy"]


def test_geschuetzte_seite_noindex(client, django_user_model):
    s = Seite.objects.create(titel="Intern", stufe=Stufe.MITGLIEDER)
    u = django_user_model.objects.create_superuser("a", "a@example.org", "pw")
    client.force_login(u)
    assert 'content="noindex' in client.get(reverse("seite", args=[s.pk])).content.decode()


def test_vorschau_trennt_absaetze():
    s = Seite(titel="x", inhalt="<p>gestellt.</p><p>Vielen Dank</p><ul><li>eins</li><li>zwei</li></ul>")
    assert s.vorschau() == "gestellt. Vielen Dank eins zwei"
