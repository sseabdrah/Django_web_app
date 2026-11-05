import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings


API_BASE = "https://api.flutterwave.com/v3"


class PaymentProviderError(Exception):
    pass


def payment_provider_ready():
    return bool(settings.FLW_SECRET_KEY and settings.FLW_SECRET_HASH)


def _request(path, payload=None):
    if not settings.FLW_SECRET_KEY:
        raise PaymentProviderError("Mobile Money payments are not configured yet.")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{API_BASE}{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {settings.FLW_SECRET_KEY}",
            "Content-Type": "application/json",
        },
        method="POST" if payload is not None else "GET",
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        raise PaymentProviderError("Could not reach the payment provider. Please try again.") from error
    if result.get("status") != "success":
        raise PaymentProviderError(result.get("message") or "The payment provider could not process this request.")
    return result


def initiate_uganda_mobile_money(payment, redirect_url):
    result = _request(
        "/charges?type=mobile_money_uganda",
        {
            "phone_number": payment.phone_number,
            "network": payment.network,
            "amount": payment.amount,
            "currency": payment.currency,
            "email": payment.user.email,
            "fullname": payment.user.full_name,
            "tx_ref": payment.tx_ref,
            "redirect_url": redirect_url,
        },
    )
    authorization = result.get("meta", {}).get("authorization", {})
    redirect = authorization.get("redirect", "")
    if authorization.get("mode") != "redirect" or not redirect.startswith("https://"):
        raise PaymentProviderError("The provider did not return a valid payment authorization page.")
    return redirect


def verify_uganda_mobile_money(transaction_id):
    return _request(f"/transactions/{transaction_id}/verify").get("data") or {}