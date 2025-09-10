# i18n_setup.py
import os
from functools import wraps
from typing import Callable

import i18n
from telegram import Update
from telegram.ext import ContextTypes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCALES_DIR = os.path.join(BASE_DIR, "locales")
i18n.load_path.append(LOCALES_DIR)
i18n.set('locale', 'fa')
i18n.set('fallback', 'en')
i18n.set('enable_memoization', False)
i18n.set('skip_locale_root_data', False)


def translate(key: str, lang: str = 'en', **kwargs) -> str:
    """
    Simple wrapper to translate a key with optional interpolation kwargs.
    """
    return i18n.t(key, locale=lang, **kwargs)


def get_lang_from_update(update: Update) -> str:
    """
    Determine language. Adjust logic as needed:
    - read from user language_code (Telegram supplied)
    - read from chat data / user_data set by your bot
    - default to 'fa'
    """
    if update.effective_user and getattr(update.effective_user, "language_code", None):
        # telegram language_code is like 'fa', 'en', 'en-US' etc.
        code = update.effective_user.language_code.split('-', 1)[0]
        if code in ('fa', 'en'):
            return code
    # fallback to chat/user stored preference if present
    try:
        ctx = update._effective_message.app  # not reliable; prefer passing Context
    except Exception:
        pass
    return 'fa'  # default


def with_locale(fn: Callable) -> Callable:
    """
    Decorator for handlers. Injects an extra kwarg `lang` into the handler
    resolved from the Update or Context. Works with async handlers.
    """

    @wraps(fn)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        # priority: context.user_data['lang'] -> user's telegram language_code -> fallback 'fa'
        lang = None
        if context and getattr(context, "user_data", None):
            lang = context.user_data.get("lang")
        if not lang and update.effective_user and getattr(update.effective_user, "language_code", None):
            lang = update.effective_user.language_code.split('-', 1)[0]
        if not lang:
            lang = 'fa'
        return await fn(update, context, lang=lang, *args, **kwargs)

    return wrapper
