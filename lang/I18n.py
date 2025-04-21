from gettext import translation

# Exemple simple avec deux langues disponibles
def get_translator(lang_code: str):
    try:
        t = translation('messages', localedir='locales', languages=[lang_code])
        t.install()
        return t.gettext
    except FileNotFoundError:
        # fallback: default to English
        return lambda s: s
