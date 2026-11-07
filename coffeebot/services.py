from decimal import Decimal, InvalidOperation
from io import BytesIO
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 25_000_000


def parse_weight(value):
    try:
        weight = Decimal(value)
        if not weight.is_finite() or weight <= 0 or weight > 10:
            raise ValueError()
        if weight != weight.quantize(Decimal('0.01')):
            raise ValueError()
        return weight
    except (InvalidOperation, ValueError):
        raise ValueError('Enter a weight above 0 and up to 10 kg, with at most two decimal places.') from None


def prepare_photo(upload):
    if not upload or not upload.filename:
        raise ValueError('Take or upload a photo of the grounds and scale reading.')
    raw = upload.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024:
        raise ValueError('The photo must be under 10 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as original:
                if original.format not in {'JPEG', 'PNG', 'WEBP'}:
                    raise ValueError('Use a JPEG, PNG or WebP photo. Convert HEIC photos to JPEG first.')
                original.load()
                rotated = ImageOps.exif_transpose(original)
                image = rotated.convert('RGB')
                image.thumbnail((1600, 1600))
                # A fresh pixel image drops EXIF/GPS/other metadata.
                clean = Image.new('RGB', image.size)
                clean.paste(image)
                output = BytesIO()
                clean.save(output, 'JPEG', quality=82, optimize=True)
                return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('That file could not be read safely. Choose a smaller JPEG, PNG or WebP photo.') from None
