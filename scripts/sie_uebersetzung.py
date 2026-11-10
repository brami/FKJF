"""Erzeugt locale/de/LC_MESSAGES/django.po/.mo: Sie-Form für die Texte von django-allauth."""
import json
import sys

import polib

SIE = [
    "Sie können Ihre primäre E-Mail-Adresse nicht löschen.",
    "Bitte geben Sie Ihr aktuelles Passwort ein.",
    "Sie können nicht mehr als %d E-Mail-Adressen hinzufügen.",
    "Ihre primäre E-Mail-Adresse muss bestätigt werden.",
    "Der Benutzername kann nicht verwendet werden. Bitte wählen Sie einen anderen.",
    "Bitte wählen Sie nur eine aus.",
    "Bitte haben Sie etwas Geduld, Sie senden zu viele Anfragen.",
    "Sie müssen zweimal dasselbe Passwort eingeben.",
    "Sie müssen zweimal dieselbe E-Mail-Adresse eingeben.",
    "Ihre Benutzer-ID ansehen",
    "Ihre E-Mail-Adresse ansehen",
    "Ihre grundlegenden Profilinformationen ansehen",
    "Es existiert bereits ein Konto mit dieser E-Mail-Adresse. Bitte melden Sie sich zuerst mit diesem Konto an und verknüpfen Sie es dann mit Ihrem %s-Konto.",
    "Für Ihr Konto wurde noch kein Passwort festgelegt.",
    "Ihr Konto hat keine bestätigte E-Mail-Adresse.",
    "Möchten Sie die ausgewählte E-Mail-Adresse wirklich entfernen?",
    "Sie erhalten diese E-Mail, weil Sie oder jemand anderes versucht hat, sich mit dieser E-Mail-Adresse für ein Konto anzumelden:\n\n%(email)s\n\nEs existiert jedoch bereits ein Konto mit dieser E-Mail-Adresse. Falls Sie das vergessen haben, verwenden Sie bitte „Passwort vergessen“, um Ihr Konto wiederherzustellen:\n\n%(password_reset_url)s",
    "Vielen Dank, dass Sie %(site_name)s nutzen!\n%(site_domain)s",
    "Bitte bestätigen Sie Ihre E-Mail-Adresse",
    "Ihr Passwort wurde geändert.",
    "Sie erhalten diese E-Mail, weil Sie oder jemand anderes das Zurücksetzen des Passworts für Ihr Konto angefordert hat.\nFalls Sie das nicht waren, können Sie diese Nachricht ignorieren. Über den folgenden Link setzen Sie Ihr Passwort zurück.",
    "Falls Sie Ihren Benutzernamen vergessen haben: Er lautet %(username)s.",
    "Ihre E-Mail-Adresse muss noch bestätigt werden.",
    "Bitte bestätigen Sie, dass <a href=\"mailto:%(email)s\">%(email)s</a> eine E-Mail-Adresse von %(user_display)s ist.",
    "Dieser Bestätigungslink ist leider abgelaufen. Bitte lassen Sie sich eine neue <a href=\"%(email_url)s\">Bestätigungs-E-Mail</a> schicken.",
    "Sie haben noch kein Konto? Dann %(link)serstellen%(end_link)s Sie bitte zunächst eines.",
    "Möchten Sie sich wirklich abmelden?",
    "Sie können Ihre primäre E-Mail-Adresse (%(email)s) nicht löschen.",
    "Sie haben die Adresse %(email)s bestätigt.",
    "Sie haben sich abgemeldet.",
    "Passwort vergessen? Geben Sie unten Ihre E-Mail-Adresse ein. Wir schicken Ihnen dann einen Link, mit dem Sie Ihr Passwort zurücksetzen können.",
    "Wir haben Ihnen eine E-Mail geschickt. Wenn Sie sie nicht in Ihrem Posteingang finden, sehen Sie bitte im Spam-Ordner nach. Ist sie nach einigen Minuten noch nicht angekommen, wenden Sie sich bitte an den Vorstand.",
    "Der Link zum Zurücksetzen des Passworts ist ungültig; möglicherweise wurde er bereits benutzt. Bitte fordern Sie einen neuen Link zum <a href=\"%(passwd_reset_url)s\">Zurücksetzen</a> an.",
    "Ihr Passwort wurde geändert.",
    "Ihre Telefonnummer muss noch bestätigt werden.",
    "Sie haben bereits ein Konto? Dann bitte %(link)shier entlang%(end_link)s.",
    "Sie sind bereits als %(user_display)s angemeldet.",
    "Sie haben derzeit keine E-Mail-Adresse hinterlegt. Ohne Adresse können wir Sie nicht benachrichtigen und Ihr Passwort nicht zurücksetzen.",
    "Bestätigen Sie Ihre E-Mail-Adresse",
    "Wir haben Ihnen eine E-Mail geschickt, um Ihre Adresse zu bestätigen. Bitte folgen Sie dem Link in der E-Mail. Wenn Sie sie nicht in Ihrem Posteingang finden, sehen Sie bitte im Spam-Ordner nach. Ist sie nach einigen Minuten noch nicht angekommen, wenden Sie sich bitte an den Vorstand.",
    "Für diesen Bereich der Webseite möchten wir sicherstellen,\ndass Sie die Person sind, für die Sie sich ausgeben.\nDazu müssen Sie Ihre E-Mail-Adresse bestätigen. ",
    "Wir haben Ihnen eine E-Mail geschickt, um Ihre\nAdresse zu bestätigen. Bitte klicken Sie auf den Link\nin der E-Mail. Wenn Sie sie nicht in Ihrem Posteingang finden, sehen Sie bitte im Spam-Ordner nach. Ist sie nach einigen Minuten noch nicht angekommen, wenden Sie sich bitte an den Vorstand.",
    "<strong>Hinweis:</strong> Sie können <a href=\"%(email_url)s\">Ihre E-Mail-Adresse ändern</a>.",
    "%(client_name)s möchte auf Ihr Konto bei %(site_name)s zugreifen.",
    "Geben Sie den auf Ihrem Gerät angezeigten Code ein.",
    "Bitte bestätigen Sie den auf Ihrem %(client_name)s angezeigten Code, um dieses Gerät zu autorisieren.",
    "Sie haben Ihr Gerät %(client_name)s erfolgreich autorisiert.",
    "Die Autorisierung für Ihr Gerät %(client_name)s wurde abgelehnt.",
    "Sie sind dabei, einen neuen Satz Wiederherstellungscodes für Ihr Konto zu erzeugen.",
    "Ich habe meine Wiederherstellungscodes gespeichert",
    "Sie sind dabei, die Anmeldung per Authenticator-App zu deaktivieren. Sind Sie sicher?",
    "Sie sind dabei, ein neues Konto von %(provider)s zu verknüpfen.",
    "Sie sind dabei, sich mit einem Konto von %(provider)s anzumelden.",
    "Sie haben die Anmeldung abgebrochen. War das ein Versehen oder ein Fehler, folgen Sie bitte diesem <a href=\"%(login_url)s\">Link</a>, um sich anzumelden.",
    "Sie verwenden Ihr %(provider_name)s-Konto, um sich bei\n%(site_name)s anzumelden. Bitte füllen Sie zum Abschluss das folgende Formular aus:",
    "Sie erhalten diese E-Mail, weil Sie oder jemand anderes das Zurücksetzen des Passworts für ein Konto angefordert hat. Zur E-Mail-Adresse %(email)s gibt es jedoch kein Konto.\n\nFalls Sie das nicht waren, können Sie diese Nachricht ignorieren.\n\nAndernfalls wenden Sie sich bitte an den Vorstand.",
    "Bitte melden Sie sich mit einem der folgenden Konten an oder <a \nhref=\"%(signup_url)s\">registrieren Sie sich bei %(site_name)s</a> und melden Sie sich dann unten an:",
    "Wir haben Ihnen eine E-Mail geschickt. Bitte wenden Sie sich an uns, wenn sie nicht innerhalb weniger Minuten ankommt.",
    "Der Benutzername ist bereits vergeben – bitte wählen Sie einen anderen.",
    "Sie haben bestätigt, dass <a href=\"mailto:%(email)s\">%(email)s</a> eine gültige Adresse von %(user_display)s ist.",
    "Vielen Dank, dass Sie unsere Seite nutzen!",
]

eintraege = json.load(open(sys.argv[1]))
assert len(eintraege) == len(SIE), (len(eintraege), len(SIE))
po = polib.POFile()
po.metadata = {
    "Project-Id-Version": "fv-web",
    "Language": "de",
    "MIME-Version": "1.0",
    "Content-Type": "text/plain; charset=UTF-8",
    "Content-Transfer-Encoding": "8bit",
    "Plural-Forms": "nplurals=2; plural=(n != 1);",
}
po.header = ("Sie-Form für Texte von django-allauth (überschreibt dessen Du-Form).\n"
             "Erzeugt mit scripts/sie_uebersetzung.py; nach Änderungen .mo neu erzeugen.")
for e, sie in zip(eintraege, SIE):
    # Platzhalter müssen erhalten bleiben
    import re
    ph = lambda t: sorted(re.findall(r"%\(\w+\)s|%[sd]", t))
    assert ph(e["str"]) == ph(sie), (e["str"], sie)
    po.append(polib.POEntry(msgid=e["id"], msgstr=sie))
po.save(sys.argv[2] + "/django.po")
po.save_as_mofile(sys.argv[2] + "/django.mo")
print(len(po), "Einträge geschrieben")
