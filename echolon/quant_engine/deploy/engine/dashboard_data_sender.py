"""
Dashboard Data Sender
=====================

Sends the generated dashboard_data.json to the DolphinQuant backend
via HTTP POST. Uses only stdlib (urllib) to avoid extra dependencies.
"""

import json
import ssl
import urllib.request
import urllib.error

try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()

from ..config.logging_config import get_deploy_logger

logger = get_deploy_logger(__name__)

DEFAULT_BACKEND_URL = 'https://dolphinquant.com'
DASHBOARD_DATA_ENDPOINT = '/api/falcon/dashboard-data/'
PORTFOLIO_DASHBOARD_ENDPOINT = '/api/falcon/portfolio-dashboard/'


def _post_json(url: str, data: dict, label: str) -> bool:
    """POST JSON data to URL. Returns True on success."""
    payload = json.dumps(data).encode('utf-8')

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'User-Agent': 'DolphinQuant-TradingRunner/1.0',
        },
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=30, context=_SSL_CONTEXT) as resp:
            status = resp.status
            body = json.loads(resp.read().decode('utf-8'))
            logger.info(f"{label} sent: {status} — {body}")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error(f"{label} send failed: HTTP {e.code} — {body}")
        return False
    except urllib.error.URLError as e:
        logger.error(f"{label} send failed: {e.reason}")
        return False
    except Exception as e:
        logger.error(f"{label} send failed: {e}")
        return False


def send_dashboard_data(
    data: dict,
    backend_url: str = DEFAULT_BACKEND_URL,
) -> bool:
    """POST single-slot dashboard data JSON to the backend."""
    url = f'{backend_url.rstrip("/")}{DASHBOARD_DATA_ENDPOINT}'
    return _post_json(url, data, "Dashboard data")


def send_portfolio_dashboard_data(
    data: dict,
    backend_url: str = DEFAULT_BACKEND_URL,
) -> bool:
    """POST portfolio dashboard data JSON to the backend."""
    url = f'{backend_url.rstrip("/")}{PORTFOLIO_DASHBOARD_ENDPOINT}'
    return _post_json(url, data, "Portfolio dashboard data")
