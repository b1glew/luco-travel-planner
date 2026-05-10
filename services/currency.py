import json
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.request import urlopen

BASE_API = "https://api.frankfurter.app/latest"
UPDATED_AT_KEY = "_updated_at"

# Default fallback rates for common currency pairs (approximate)
DEFAULT_RATES = {
    "GBP_EUR": 1.17,
    "GBP_USD": 1.27,
    "GBP_AUD": 1.94,
    "GBP_CAD": 1.73,
    "GBP_JPY": 189.0,
    "EUR_USD": 1.09,
    "EUR_AUD": 1.66,
    "EUR_CAD": 1.48,
    "EUR_JPY": 161.0,
    "USD_AUD": 1.52,
    "USD_CAD": 1.36,
    "USD_JPY": 147.0,
}


def fetch_exchange_rates(base_currency, currencies, cache):
    """Fetch live exchange rates from the API and cache them."""
    targets = sorted(set(currencies) - {base_currency})
    if not targets:
        return cache

    symbols = ",".join(targets)
    url = f"{BASE_API}?from={base_currency}&to={symbols}"
    try:
        with urlopen(url, timeout=10) as response:
            data = json.load(response)
            for target, rate in data.get("rates", {}).items():
                cache[f"{base_currency}_{target}"] = rate
                if rate:
                    cache[f"{target}_{base_currency}"] = 1.0 / rate
            cache[f"{base_currency}_{base_currency}"] = 1.0
            for target in targets:
                cache[f"{target}_{target}"] = 1.0
            cache[UPDATED_AT_KEY] = datetime.now(timezone.utc).isoformat()
            return cache
    except (URLError, KeyError, json.JSONDecodeError):
        # Silently fail and fall back to defaults
        return cache


def convert(amount, frm, to, cache):
    """Convert amount from one currency to another using cached or fallback rates."""
    if frm == to or amount == 0:
        return amount

    key = f"{frm}_{to}"
    if key in cache:
        return amount * cache[key]

    reverse_key = f"{to}_{frm}"
    if reverse_key in cache and cache[reverse_key] != 0:
        return amount / cache[reverse_key]

    if key in DEFAULT_RATES:
        return amount * DEFAULT_RATES[key]

    reverse_default = f"{to}_{frm}"
    if reverse_default in DEFAULT_RATES:
        rate = 1.0 / DEFAULT_RATES[reverse_default]
        return amount * rate

    return amount
