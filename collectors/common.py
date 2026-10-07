from __future__ import annotations

import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "MoCoFederalContractTracker/1.0 (+https://github.com/)"


def session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=0.7, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET", "POST"))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json,text/html;q=0.9,*/*;q=0.8"})
    return s


def get(url: str, *, timeout: int = 30, **kwargs: Any) -> requests.Response:
    response = session().get(url, timeout=timeout, **kwargs)
    response.raise_for_status()
    time.sleep(0.15)
    return response


def post(url: str, *, timeout: int = 45, **kwargs: Any) -> requests.Response:
    response = session().post(url, timeout=timeout, **kwargs)
    response.raise_for_status()
    time.sleep(0.15)
    return response
