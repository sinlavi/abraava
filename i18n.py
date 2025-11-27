import gettext
import os

BASE_DIR = os.path.dirname(__file__)
LOCALES_DIR = os.path.join(BASE_DIR, "locales")


def translate(key: str, lang: str = None, context=None) -> str:
    """Translate a key using gettext/Babel system."""
    try:
        lang = context.user_data.get("lang", "fa") if lang is None else lang
        trans = gettext.translation("messages", localedir=LOCALES_DIR, languages=[lang])
        trans.install()
        return trans.gettext(key)
    except FileNotFoundError:
        return key
