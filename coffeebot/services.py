from decimal import Decimal, InvalidOperation
from io import BytesIO
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError
from supabase import create_client

Image.MAX_IMAGE_PIXELS = 25_000_000


class AuthRejected(Exception):
    """Credentials or registration data were rejected without exposing provider details."""


class AuthUnavailable(Exception):
    """The external identity service could not complete the request."""


class SupabaseAuthService:
    """Creates a fresh publishable-key client for every auth operation.

    The service-secret database client is deliberately never used for user sign-in,
    so auth state cannot leak between Gunicorn threads.
    """

    def __init__(self, url, publishable_key, redirect_url=''):
        self.url = url
        self.publishable_key = publishable_key
        self.redirect_url = redirect_url

    def _client(self):
        if not self.url or not self.publishable_key:
            raise AuthUnavailable()
        return create_client(self.url, self.publishable_key)

    def register(self, email, password, profile):
        options = {'data': profile}
        if self.redirect_url:
            options['email_redirect_to'] = self.redirect_url
        try:
            response = self._client().auth.sign_up({
                'email': email,
                'password': password,
                'options': options,
            })
            if not response.user:
                raise AuthRejected()
            return {
                'user_id': str(response.user.id),
                'confirmation_required': response.session is None,
            }
        except (AuthRejected, AuthUnavailable):
            raise
        except Exception as error:
            message = str(error).lower()
            if any(term in message for term in ('password', 'registered', 'email', 'signup')):
                raise AuthRejected() from None
            raise AuthUnavailable() from None

    def authenticate(self, email, password):
        try:
            response = self._client().auth.sign_in_with_password({
                'email': email,
                'password': password,
            })
            if not response.user:
                raise AuthRejected()
            return {'user_id': str(response.user.id), 'email': response.user.email}
        except (AuthRejected, AuthUnavailable):
            raise
        except Exception as error:
            message = str(error).lower()
            if any(term in message for term in ('credential', 'password', 'email', 'confirmed', 'invalid')):
                raise AuthRejected() from None
            raise AuthUnavailable() from None


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


def parse_remaining_weight(value, weight_before):
    try:
        remaining = Decimal(value)
        before = Decimal(str(weight_before))
        if not remaining.is_finite() or remaining < 0 or remaining >= before:
            raise ValueError()
        if remaining != remaining.quantize(Decimal('0.01')):
            raise ValueError()
        return remaining
    except (InvalidOperation, ValueError):
        raise ValueError(
            'Enter the new scale reading. It must be at least 0 kg and lower than the starting weight, '
            'with at most two decimal places.'
        ) from None


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
