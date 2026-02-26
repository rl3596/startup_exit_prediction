"""
Core HTTP client for the Crunchbase API v4.

Features:
- Token-bucket rate limiter (respects Basic 60 RPM / Enterprise 200 RPM)
- Exponential backoff on network errors
- 429 handling via Retry-After header
- AccessTierError on 403 (caller handles gracefully)
- PermissionError on 401 (bad API key)
"""

import time
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

logger = logging.getLogger(__name__)


class AccessTierError(Exception):
    """Raised when an endpoint returns 403 due to insufficient API access tier."""
    pass


class RateLimiter:
    """Simple token-bucket rate limiter scoped to requests/minute."""

    def __init__(self, rpm: int):
        self.set_rpm(rpm)
        self._last_call = 0.0

    def set_rpm(self, rpm: int):
        self.min_interval = 60.0 / max(rpm, 1)

    def wait(self):
        elapsed = time.monotonic() - self._last_call
        gap = self.min_interval - elapsed
        if gap > 0:
            time.sleep(gap)
        self._last_call = time.monotonic()


class CrunchbaseClient:
    """
    Crunchbase API v4 HTTP client.

    Usage:
        client = CrunchbaseClient()
        data = client._get("entities/organizations/openai")
        data = client._post("searches/organizations", body={...})
    """

    def __init__(self):
        self.session      = requests.Session()
        self.rate_limiter = RateLimiter(config.RATE_LIMIT_RPM)

        # urllib3-level retry only for transient network/server errors.
        # 429 is handled manually so we can read the Retry-After header.
        adapter = HTTPAdapter(
            max_retries=Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[500, 502, 503, 504],
                allowed_methods=["GET", "POST"],
            )
        )
        self.session.mount("https://", adapter)
        self.session.headers.update({"Content-Type": "application/json"})

    def set_rate_limit(self, rpm: int):
        self.rate_limiter.set_rpm(rpm)
        logger.info("Rate limit set to %d RPM", rpm)

    # ------------------------------------------------------------------ #
    #  Public HTTP helpers                                                 #
    # ------------------------------------------------------------------ #

    def _get(self, path: str, params: dict = None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, body: dict, params: dict = None) -> dict:
        return self._request("POST", path, json_body=body, params=params)

    # ------------------------------------------------------------------ #
    #  Internal request with retry / rate-limit logic                     #
    # ------------------------------------------------------------------ #

    def _request(self, method: str, path: str,
                 params: dict = None, json_body: dict = None) -> dict:
        url           = f"{config.BASE_URL}/{path.lstrip('/')}"
        merged_params = {**config.AUTH_PARAM, **(params or {})}

        for attempt in range(config.MAX_RETRIES):
            self.rate_limiter.wait()

            try:
                resp = self.session.request(
                    method, url,
                    params=merged_params,
                    json=json_body,
                    timeout=30,
                )
            except requests.RequestException as exc:
                wait = config.BACKOFF_BASE_SECS ** attempt
                logger.warning(
                    "Network error (attempt %d/%d): %s — retrying in %ds",
                    attempt + 1, config.MAX_RETRIES, exc, wait
                )
                time.sleep(wait)
                continue

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                logger.warning("Rate-limited (429). Sleeping %ds", retry_after)
                time.sleep(retry_after)
                continue

            if resp.status_code == 401:
                raise PermissionError(
                    "API key rejected (401). Check CB_API_KEY environment variable."
                )

            if resp.status_code == 403:
                raise AccessTierError(
                    f"403 Forbidden: {method} {path} — endpoint requires higher access tier."
                )

            if resp.status_code == 404:
                logger.warning("404 Not Found: %s %s", method, path)
                return {}

            if resp.status_code == 400:
                logger.error("400 Bad Request: %s %s — body: %s",
                             method, path, resp.text[:500])
                resp.raise_for_status()

            resp.raise_for_status()
            return resp.json()

        raise RuntimeError(
            f"Request failed after {config.MAX_RETRIES} attempts: {method} {path}"
        )
