from telegram import Update

import i18n
import os

# Configure python-i18n
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCALES_DIR = os.path.join(BASE_DIR, "locales")

# Initialize i18n

i18n.load_path.append(LOCALES_DIR)
i18n.set('fallback', 'fa')
i18n.set('enable_memoization', True)

def translate(key: str, lang: str = 'fa') -> str:
    return i18n.t(key, locale=lang)

from telegram.ext import CommandHandler

