"""Système d'internationalisation (i18n) modulaire pour RotGuard.

Charge dynamiquement les dictionnaires de traduction situés dans core/locales/.
Toute nouvelle langue ajoutée sous forme de module core/locales/<lang>.py est
automatiquement détectée et intégrée dans le menu déroulant.
"""

import importlib
import locale
import os
import pkgutil
import sys
from typing import Dict, Any, Optional, List, Tuple

import core.locales
from core.locales import fr, en

# Registre des langues disponibles : code -> {"name": str, "translations": dict}
AVAILABLE_LOCALES: Dict[str, Dict[str, Any]] = {
    "fr": {
        "name": getattr(fr, "LANGUAGE_NAME", "Français"),
        "translations": getattr(fr, "TRANSLATIONS", {})
    },
    "en": {
        "name": getattr(en, "LANGUAGE_NAME", "English"),
        "translations": getattr(en, "TRANSLATIONS", {})
    }
}


def _discover_locales():
    """Découvre et charge automatiquement tout fichier de langue présent dans core/locales/."""
    try:
        package_path = os.path.dirname(core.locales.__file__)
        for _, module_name, is_pkg in pkgutil.iter_modules([package_path]):
            if is_pkg or module_name.startswith("_"):
                continue
            if module_name in AVAILABLE_LOCALES:
                continue
            try:
                mod = importlib.import_module(f"core.locales.{module_name}")
                code = getattr(mod, "LANGUAGE_CODE", module_name)
                name = getattr(mod, "LANGUAGE_NAME", module_name.capitalize())
                translations = getattr(mod, "TRANSLATIONS", {})
                if translations:
                    AVAILABLE_LOCALES[code] = {
                        "name": name,
                        "translations": translations
                    }
            except Exception:
                pass
    except Exception:
        pass


# Découverte initiale
_discover_locales()

CURRENT_LANGUAGE = "fr"
CONFIGURED_LANGUAGE = "auto"


def detect_system_language() -> str:
    """Détecte la langue préférée de l'environnement OS (Français par défaut si non anglais)."""
    try:
        loc = locale.getdefaultlocale()[0]
        if loc and loc.lower().startswith("en"):
            return "en"
    except Exception:
        pass

    lang_env = os.environ.get("LANG", "").lower()
    if lang_env.startswith("en"):
        return "en"

    return "fr"


def set_active_language(lang_code: str):
    """Définit la langue active ('auto', ou un code de langue tel que 'fr', 'en', etc.)."""
    global CURRENT_LANGUAGE, CONFIGURED_LANGUAGE
    CONFIGURED_LANGUAGE = lang_code or "auto"

    if CONFIGURED_LANGUAGE == "auto":
        sys_lang = detect_system_language()
        CURRENT_LANGUAGE = sys_lang if sys_lang in AVAILABLE_LOCALES else "fr"
    elif CONFIGURED_LANGUAGE in AVAILABLE_LOCALES:
        CURRENT_LANGUAGE = CONFIGURED_LANGUAGE
    else:
        CURRENT_LANGUAGE = "fr"


def get_active_language() -> str:
    """Retourne le code de langue effectif actuellement appliqué ('fr', 'en', ...)."""
    return CURRENT_LANGUAGE


def get_configured_language() -> str:
    """Retourne la valeur de réglage configurée ('auto', 'fr', 'en', ...)."""
    return CONFIGURED_LANGUAGE


def get_available_languages() -> List[Tuple[str, str]]:
    """Retourne la liste des langues pour le menu déroulant :
    - 'auto' (par défaut du système) en tout premier.
    - Suivi de toutes les langues installées, triées par ordre alphabétique de leur nom.
    Format : [(code, libellé_affiché), ...]
    """
    auto_label = tr("lang_auto")
    result: List[Tuple[str, str]] = [("auto", auto_label)]

    # Tri alphabétique des langues disponibles selon leur nom
    other_langs = []
    for code, data in AVAILABLE_LOCALES.items():
        other_langs.append((code, data["name"]))

    other_langs.sort(key=lambda item: item[1].lower())
    result.extend(other_langs)
    return result


def tr(key: str, *args) -> str:
    """Traduit une clé dans la langue active avec arguments de formatage éventuels."""
    locale_data = AVAILABLE_LOCALES.get(CURRENT_LANGUAGE)
    text = None
    if locale_data:
        text = locale_data["translations"].get(key)

    # Repli sur le français si la clé est absente dans la langue active
    if text is None:
        fr_data = AVAILABLE_LOCALES.get("fr")
        if fr_data:
            text = fr_data["translations"].get(key)

    if text is None:
        text = key

    if args:
        try:
            return text.format(*args)
        except Exception:
            return text
    return text


def format_bytes(bytes_val: int) -> str:
    """Formate une taille d'octets avec les unités localisées selon la langue active."""
    if bytes_val >= 1024 ** 4:
        return f"{bytes_val / (1024 ** 4):.2f} {tr('unit_tb')}"
    if bytes_val >= 1024 ** 3:
        return f"{bytes_val / (1024 ** 3):.2f} {tr('unit_gb')}"
    if bytes_val >= 1024 ** 2:
        return f"{bytes_val / (1024 ** 2):.1f} {tr('unit_mb')}"
    if bytes_val >= 1024:
        return f"{bytes_val / 1024:.0f} {tr('unit_kb')}"
    return f"{bytes_val} {tr('unit_b')}"
