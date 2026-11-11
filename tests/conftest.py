import pytest


@pytest.fixture(autouse=True)
def _ohne_zwei_faktor_pflicht(settings):
    """Die meisten Tests prüfen anderes; die Pflicht wird in test_konto.py eigens getestet."""
    settings.FV_ZWEI_FAKTOR_PFLICHT = False
