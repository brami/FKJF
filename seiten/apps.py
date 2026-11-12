from django.apps import AppConfig


class SeitenConfig(AppConfig):
    name = "seiten"

    def ready(self):
        from . import mail
        mail.signale_verbinden()
