import gettext
import os

BASE_DIR = os.path.dirname(__file__)
LOCALES_DIR = os.path.join(BASE_DIR, "locales")


def translate(key: str, lang: str = "en") -> str:
    """Translate a key using gettext/Babel system."""
    try:
        trans = gettext.translation("messages", localedir=LOCALES_DIR, languages=[lang])
        trans.install()
        return trans.gettext(key)
    except FileNotFoundError:
        # fallback to English if missing
        return key
