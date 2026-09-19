"""Angel One SmartAPI — live NSE prices, and daily candles when NSE's own file is missing.

⚠ **This module can only read prices, by construction.** It contains the address of exactly
three routes: login, quote and daily candles. The account behind it is a demat account, and
SmartAPI's order, holdings, positions and GTT routes all live on this same host — but none of
their addresses are written here, so nothing in this codebase can place or inspect a trade,
whether by a bug, a prompt injection reaching a tool, or a future edit made in a hurry.
`tests/test_marketdata_adapters.py` asserts the module names no other route. That is a
stronger guarantee than wrapping Angel's SDK in a deny-list, which is why the SDK is not used.

⚠ **The static IP registered on the SmartAPI app gates orders only** (SEBI, April 2026).
Measured: login, quote and candles all succeeded from an unregistered laptop IP.

⚠ **This host goes dark.** During the build, `apiconnect.angelone.in` refused TCP connections
for over an hour while Angel's other hosts answered. That is why the close of record comes
from NSE (`nse.py`) and this module is only asked for what a broker uniquely has: the price
while the market is open.
"""

from __future__ import annotations

import datetime as dt
import socket
import threading
import uuid
from decimal import Decimal

import httpx
import pyotp

from app.config import settings
from app.services.marketdata import http
from app.services.marketdata.http import ProviderError

PROVIDER = "ANGEL_ONE"
ROOT = "https://apiconnect.angelone.in"

_LOGIN = "/rest/auth/angelbroking/user/v1/loginByPassword"
_QUOTE = "/rest/secure/angelbroking/market/v1/quote"
_CANDLES = "/rest/secure/angelbroking/historical/v1/getCandleData"

#: The complete list of routes this module may call. See the module docstring.
ROUTES = (_LOGIN, _QUOTE, _CANDLES)

#: SmartAPI rejects a daily-candle span much over 2,000 days; stay well inside it.
_CANDLE_SPAN_DAYS = 1000

_lock = threading.Lock()
_jwt: str | None = None


def configured() -> bool:
    return all(
        (
            settings.angel_one_api_key,
            settings.angel_one_client_code,
            settings.angel_one_mpin,
            settings.angel_one_totp_secret,
        )
    )


def _headers(jwt: str | None = None) -> dict[str, str]:
    """SmartAPI's required headers.

    The IP and MAC headers are required to be present and are not validated for price
    routes — Angel's own SDK sends a hard-coded public IP for every user. Real local values
    are sent anyway rather than inventing one.
    """
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        local_ip = "127.0.0.1"
    node = uuid.getnode()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-ClientLocalIP": local_ip,
        "X-ClientPublicIP": local_ip,
        "X-MACAddress": ":".join(f"{(node >> s) & 0xFF:02x}" for s in range(40, -1, -8)),
        "X-PrivateKey": settings.angel_one_api_key,
    }
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"
    return headers


def _login(c: httpx.Client) -> str:
    def attempt() -> httpx.Response:
        r = c.post(
            ROOT + _LOGIN,
            headers=_headers(),
            json={
                "clientcode": settings.angel_one_client_code,
                "password": settings.angel_one_mpin,
                "totp": pyotp.TOTP(settings.angel_one_totp_secret).now(),
            },
        )
        r.raise_for_status()
        return r

    body = http.json_decimal(http.with_retries(PROVIDER, attempt))
    if not body.get("status"):
        # errorcode and message only: Angel echoes nothing sensitive in either.
        raise ProviderError(PROVIDER, f"login refused ({body.get('errorcode') or 'no code'})")
    return body["data"]["jwtToken"]


def _session(c: httpx.Client, *, renew: bool = False) -> str:
    global _jwt
    with _lock:
        if renew or _jwt is None:
            _jwt = _login(c)
        return _jwt


def reset_session() -> None:
    """Forget the cached session. For tests, and for a key rotated while running."""
    global _jwt
    with _lock:
        _jwt = None


def _post(c: httpx.Client, route: str, payload: dict):
    """POST to a secure route; on any refusal, log in afresh once and retry.

    ⚠ Any refusal, not a list of "session expired" codes. SmartAPI has several such codes and
    they are not all documented; matching a list that missed one would leave a dead session
    cached, and every call after it would fail until the process restarted. One extra login
    on a genuine refusal is the cheaper mistake.
    """
    if route not in ROUTES:  # a guard, not decoration: see the module docstring
        raise ProviderError(PROVIDER, "route not permitted")

    for renew in (False, True):
        jwt = _session(c, renew=renew)

        def attempt(jwt: str = jwt) -> httpx.Response:
            r = c.post(ROOT + route, headers=_headers(jwt), json=payload)
            if r.status_code in (401, 403):
                return r  # handled below as an expired session, not as a failure
            r.raise_for_status()
            return r

        r = http.with_retries(PROVIDER, attempt)
        body = http.json_decimal(r) if r.content else {}
        if not body.get("status") and not renew:
            continue
        if not body.get("status"):
            raise ProviderError(PROVIDER, f"refused ({body.get('errorcode') or r.status_code})")
        return body.get("data")
    raise ProviderError(PROVIDER, "session could not be renewed")


def quote_ltp(tokens: list[str], c: httpx.Client | None = None) -> dict[str, Decimal]:
    """Last traded price for each NSE token. Tokens Angel could not price are simply absent."""
    if not tokens:
        return {}
    own = c is None
    c = c or http.client()
    try:
        data = _post(c, _QUOTE, {"mode": "LTP", "exchangeTokens": {"NSE": list(tokens)}})
    finally:
        if own:
            c.close()
    out: dict[str, Decimal] = {}
    for row in (data or {}).get("fetched") or []:
        ltp = row.get("ltp")
        if ltp is not None and Decimal(ltp) > 0:
            out[str(row["symbolToken"])] = Decimal(ltp)
    return out


def daily_candles(
    token: str, start: dt.date, end: dt.date, c: httpx.Client | None = None
) -> list[tuple[dt.date, Decimal]]:
    """Daily closes for one NSE token, oldest first.

    ⚠ Angel stamps a daily candle `YYYY-MM-DDT00:00:00+05:30` — the *start* of the session's
    day. Only the date is taken from it; the caller stamps the close at 15:30, when it
    actually happened.
    """
    own = c is None
    c = c or http.client()
    out: dict[dt.date, Decimal] = {}
    try:
        cursor = start
        while cursor <= end:
            stop = min(end, cursor + dt.timedelta(days=_CANDLE_SPAN_DAYS))
            data = _post(
                c,
                _CANDLES,
                {
                    "exchange": "NSE",
                    "symboltoken": token,
                    "interval": "ONE_DAY",
                    "fromdate": f"{cursor:%Y-%m-%d} 09:15",
                    "todate": f"{stop:%Y-%m-%d} 15:30",
                },
            )
            for row in data or []:
                day = dt.datetime.fromisoformat(str(row[0])).date()
                out[day] = Decimal(row[4])
            cursor = stop + dt.timedelta(days=1)
    finally:
        if own:
            c.close()
    return sorted(out.items())
