"""Small JSON settings file (language, ports, setup state) — separate from the rules in config.yaml."""
import json
import subprocess

from . import paths

LABEL_PREFIX = "com.github.vvyssen.timetrace"


def system_lang():
    try:
        out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True, timeout=5).stdout
        first = next((x.strip(' ",()') for x in out.splitlines() if x.strip(' ",()')), "")
        return "zh" if first.lower().startswith("zh") else "en"
    except Exception:
        return "en"


def system_region():
    try:
        loc = subprocess.run(["defaults", "read", "-g", "AppleLocale"], capture_output=True, text=True, timeout=5).stdout.strip()
        return loc.split("_")[1][:2].lower() if "_" in loc else "us"
    except Exception:
        return "us"


def defaults():
    region = system_region()
    stores = [region] if region == "us" else [region, "us"]
    return {
        "lang": system_lang(),
        "aw_url": "http://127.0.0.1:5600",
        "port": 27181,
        "setup_done": False,
        "storefronts": stores,  # App Store regions used to name iPhone/iPad apps
    }


def load():
    data = defaults()
    try:
        data.update(json.loads(paths.SETTINGS.read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return data


def save(**changes):
    paths.ensure_dirs()
    data = load()
    data.update(changes)
    paths.SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return data
