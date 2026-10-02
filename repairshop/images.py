"""Photo validation and normalisation for evidence images, without any UI toolkit.

The backend receives a photo as bytes (a browser upload or camera capture) and stores
one normalised JPEG. Presentation layers that hold images in their own type register a
converter with `register_adapter`, so the core never imports a UI framework.
"""
from io import BytesIO
from PIL import Image, ImageOps, UnidentifiedImageError
from .domain import RuleError

MAX_BYTES = 50 * 1024 ** 2
MAX_PIXELS = 80_000_000
MAX_EDGE = 1920
QUALITY = 90
_adapters = []


def register_adapter(convert):
    """`convert(image) -> bytes | None`: turn a toolkit image into encoded bytes, or decline."""
    if convert not in _adapters:
        _adapters.append(convert)


def _raw(image):
    if isinstance(image, (bytes, bytearray, memoryview)):
        return bytes(image)
    for convert in _adapters:
        data = convert(image)
        if data is not None:
            return data
    return None


def normalise(image):
    """Validate one photo and return it as an upright JPEG at most 1920 px on its long edge."""
    data = _raw(image)
    if not data:
        raise RuleError('Photo capture failed. Retake the photo and try again.')
    if len(data) > MAX_BYTES:
        raise RuleError('Choose a photo smaller than 50 MB.')
    try:
        with Image.open(BytesIO(data)) as probe:
            if probe.width * probe.height > MAX_PIXELS:
                raise RuleError('Choose a supported image with at most 80 million pixels.')
            probe.verify()
        with Image.open(BytesIO(data)) as picture:
            picture = ImageOps.exif_transpose(picture)
            if max(picture.size) > MAX_EDGE:
                picture.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
            if picture.mode not in ('RGB', 'L'):
                background = Image.new('RGB', picture.size, 'white')
                rgba = picture.convert('RGBA')
                background.paste(rgba, mask=rgba.getchannel('A'))
                picture = background
            out = BytesIO()
            picture.convert('RGB').save(out, 'JPEG', quality=QUALITY)
            return out.getvalue()
    except RuleError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise RuleError('The photo could not be read. Use a JPEG, PNG or WebP image and try again.') from None


def solid(width=64, height=64, colour=(104, 163, 152)):
    """A plain test or placeholder image, encoded as PNG bytes."""
    out = BytesIO()
    Image.new('RGB', (width, height), colour).save(out, 'PNG')
    return out.getvalue()
