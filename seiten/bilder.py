"""Bilder unter den Anhängen: prüfen, Metadaten entfernen, verkleinerte Fassungen.

Jedes hochgeladene Bild (JPG, PNG, WebP) wird neu geschrieben:
- ohne EXIF- und sonstige Metadaten (Handyfotos enthalten oft GPS-Koordinaten),
- richtig gedreht (EXIF-Ausrichtung wird angewendet),
- in drei Größen: Original (höchstens 2400 px), Seite (1200 px), Vorschau (600 px).
Fotos werden als JPEG, Grafiken mit Transparenz als PNG gespeichert.
SVG ist bewusst nicht erlaubt (kann Skripte enthalten).
"""

from io import BytesIO
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

BILD_ENDUNGEN = {"jpg", "jpeg", "png", "webp"}
GROESSEN = {"datei": 2400, "bild": 1200, "vorschau": 600}
MAX_PIXEL = 60_000_000          # Schutz vor "Dekompressionsbomben" (ca. 60 Megapixel)
Image.MAX_IMAGE_PIXELS = MAX_PIXEL


def ist_bildname(name: str) -> bool:
    return Path(name).suffix.lower().lstrip(".") in BILD_ENDUNGEN


def pruefe_bild(datei):
    """Validator: Dateien mit Bild-Endung müssen auch wirklich lesbare Bilder sein."""
    if not ist_bildname(datei.name):
        return
    try:
        pos = datei.tell()
        with Image.open(datei) as img:
            if img.width * img.height > MAX_PIXEL:
                raise ValidationError("Das Bild ist zu groß (mehr als 60 Megapixel).")
            img.verify()
        datei.seek(pos)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError):
        raise ValidationError("Die Datei ist kein lesbares Bild (JPG, PNG oder WebP).")


def _laden(datei) -> Image.Image:
    datei.seek(0)
    img = Image.open(datei)
    img.load()
    img = ImageOps.exif_transpose(img)   # Drehung anwenden, bevor die EXIF-Daten wegfallen
    transparent = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    img = img.convert("RGBA" if transparent else "RGB")
    return img


def _speichern(img: Image.Image, max_px: int) -> tuple[bytes, str]:
    kopie = img.copy()
    kopie.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
    puffer = BytesIO()
    if kopie.mode == "RGBA":
        kopie.save(puffer, "PNG", optimize=True)         # ohne Metadaten
        return puffer.getvalue(), ".png"
    kopie.save(puffer, "JPEG", quality=85, optimize=True, progressive=True)  # ohne EXIF
    return puffer.getvalue(), ".jpg"


def fassungen(datei, originalname: str) -> dict[str, ContentFile]:
    """Erzeugt die drei Fassungen eines Bildes als ContentFile (Schlüssel wie GROESSEN)."""
    img = _laden(datei)
    stamm = Path(originalname).stem
    erg = {}
    for feld, max_px in GROESSEN.items():
        daten, endung = _speichern(img, max_px)
        erg[feld] = ContentFile(daten, name=f"{stamm}{endung}")
    return erg
