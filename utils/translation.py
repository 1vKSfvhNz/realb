import json
import os
from typing import Dict

LOCALES_PATH = "locales"
LANG_CACHE: Dict[str, Dict[str, str]] = {}

def load_translations(lang: str) -> Dict[str, str]:
    """Charge les traductions pour une langue donnée, avec fallback sur 'en'."""
    if lang in LANG_CACHE:
        return LANG_CACHE[lang]

    path = os.path.join(LOCALES_PATH, f"{lang}.json")

    # Fallback si le fichier n'existe pas
    if not os.path.isfile(path):
        fallback_path = os.path.join(LOCALES_PATH, "en.json")
        if not os.path.isfile(fallback_path):
            raise FileNotFoundError("Fichier de traduction 'en.json' introuvable.")
        path = fallback_path

    with open(path, "r", encoding="utf-8") as f:
        translations = json.load(f)
        LANG_CACHE[lang] = translations

    return LANG_CACHE[lang]

def translate(lang: str, key: str, **kwargs) -> str:
    """Retourne la traduction d'une clé formatée avec des paramètres."""
    translations = load_translations(lang)
    text = translations.get(key, key)
    try:
        return text.format(**kwargs)
    except KeyError:
        return text  # En cas de paramètre manquant, retourne la chaîne brute
