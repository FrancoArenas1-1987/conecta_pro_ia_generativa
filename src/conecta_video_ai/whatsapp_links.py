from __future__ import annotations

from urllib.parse import parse_qsl, quote, urlparse

DEFAULT_CLIENT_PHONE = "56983434503"
DEFAULT_PROVIDER_PHONE = "56961903199"
DEFAULT_WHATSAPP_TEXT = ""


def _digits(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def whatsapp_click_url(phone: str, *, text: str = DEFAULT_WHATSAPP_TEXT) -> str:
    digits = _digits(phone)
    if not digits:
        digits = DEFAULT_CLIENT_PHONE
    suffix = f"&text={quote(text)}" if text else ""
    return f"https://api.whatsapp.com/send?phone={digits}{suffix}"


def extract_whatsapp_phone(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    if value.startswith(("wa.me/", "whatsapp.me/", "api.whatsapp.com/")):
        value = f"https://{value}"

    parsed = urlparse(value)
    host = (parsed.netloc or "").lower()
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))

    if "whatsapp.com" in host:
        digits = _digits(query.get("phone", ""))
        if digits:
            return f"+{digits}"

    if "wa.me" in host or "whatsapp.me" in host:
        digits = _digits(parsed.path)
        if digits:
            return f"+{digits}"

    digits = _digits(value)
    return f"+{digits}" if digits else ""


def normalize_whatsapp_click_url(
    url: str | None,
    *,
    fallback_phone: str = DEFAULT_CLIENT_PHONE,
    text: str = DEFAULT_WHATSAPP_TEXT,
) -> str:
    value = str(url or "").strip()
    if not value:
        return whatsapp_click_url(fallback_phone, text=text)
    if value.startswith(("wa.me/", "whatsapp.me/", "api.whatsapp.com/")):
        value = f"https://{value}"

    parsed = urlparse(value)
    host = (parsed.netloc or "").lower()
    if "wa.me" not in host and "whatsapp.me" not in host and "whatsapp.com" not in host:
        return value

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    detected_phone = extract_whatsapp_phone(value)
    digits = _digits(detected_phone or fallback_phone)
    message = query.get("text") or text
    return whatsapp_click_url(digits, text=message)
