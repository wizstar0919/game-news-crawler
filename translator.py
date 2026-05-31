import json
import hashlib
import re
import threading
from pathlib import Path
from deep_translator import GoogleTranslator

CACHE_FILE = Path(__file__).parent / ".translation_cache.json"
_lock = threading.Lock()
_cache: dict = {}


def _load_cache() -> dict:
    global _cache
    if _cache:
        return _cache
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    return _cache


def _save_cache() -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False)
    except Exception:
        pass


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _is_korean(text: str) -> bool:
    if not text:
        return False
    hangul = sum(1 for c in text if "가" <= c <= "힣")
    return hangul / max(len(text), 1) > 0.15


def translate_to_korean(text: str) -> str:
    if not text or not text.strip():
        return ""
    if _is_korean(text):
        return text

    text = re.sub(r"\s+", " ", text).strip()[:4500]
    cache = _load_cache()
    k = _key(text)
    if k in cache:
        return cache[k]

    try:
        with _lock:
            result = GoogleTranslator(source="auto", target="ko").translate(text)
        if result:
            cache[k] = result
            _save_cache()
            return result
    except Exception as e:
        print(f"[translator] failed: {e}")
    return text
