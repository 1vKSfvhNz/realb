import json
import os

LOCALES_PATH = "locales"
LANG_CACHE = {}

def load_translations(lang: str):
    if lang in LANG_CACHE:
        return LANG_CACHE[lang]

    path = os.path.join(LOCALES_PATH, f"{lang}.json")
    if not os.path.exists(path):
        path = os.path.join(LOCALES_PATH, "en.json")  # fallback

    with open(path, "r", encoding="utf-8") as f:
        LANG_CACHE[lang] = json.load(f)

    return LANG_CACHE[lang]

def translate(lang: str, key: str) -> str:
    translations = load_translations(lang)
    return translations.get(key, key)
