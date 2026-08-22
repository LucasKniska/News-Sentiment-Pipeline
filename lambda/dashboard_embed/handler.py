import base64
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_HEADERS = {"Content-Type": "application/json"}

# No login system on the static frontend - every visitor gets the same
# published dashboard, so these are fixed placeholders rather than derived
# from a real per-user identity. external_viewer_id/external_value exist in
# Databricks' embedding API for per-viewer row-level data filtering, which
# this project doesn't use.
_EXTERNAL_VIEWER_ID = "portfolio-site"
_EXTERNAL_VALUE = "public"


def _post_form(url: str, data: dict, client_id: str, client_secret: str) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    req.add_header("Authorization", f"Basic {basic}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _get(url: str, bearer_token: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {bearer_token}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def fetch_dashboard_embed_token() -> dict:
    """Runs the 3-call Databricks external-embedding OAuth exchange (service
    principal auth -> dashboard-scoped tokeninfo -> tightly-scoped embed
    token) and returns what the frontend's @databricks/aibi-client needs.
    """
    host = os.environ["DATABRICKS_HOST"]
    org_id = os.environ["DATABRICKS_ORG_ID"]
    dashboard_id = os.environ["DATABRICKS_DASHBOARD_ID"]
    client_id = os.environ["DATABRICKS_SP_CLIENT_ID"]
    client_secret = os.environ["DATABRICKS_SP_CLIENT_SECRET"]

    token_url = f"{host}/oidc/v1/token?o={org_id}"

    # Step 1: broad service-principal access token.
    broad = _post_form(
        token_url,
        {"grant_type": "client_credentials", "scope": "all-apis"},
        client_id,
        client_secret,
    )

    # Step 2: dashboard-scoped authorization_details for this viewer - this
    # is what actually depends on the service principal's CAN RUN grant on
    # the published dashboard.
    tokeninfo_url = (
        f"{host}/api/2.0/lakeview/dashboards/{dashboard_id}/published/tokeninfo"
        f"?o={org_id}&external_viewer_id={_EXTERNAL_VIEWER_ID}&external_value={_EXTERNAL_VALUE}"
    )
    tokeninfo = _get(tokeninfo_url, broad["access_token"])

    # Step 3: exchange for the tightly-scoped, 1-hour embed token. Forward
    # every field tokeninfo returned (not just authorization_details) - it
    # also carries a "scope" claim (e.g. "dashboards.lakeview-embedded:read
    # ...") that the embed API rejects the token without. Dropping it here
    # previously produced a token with an empty scope claim, which the
    # dashboard viewer API rejects with a 403 "does not have required
    # scopes: dashboards" even though authorization_details/CAN RUN were
    # both correct.
    scoped_params = dict(tokeninfo)
    scoped_params["authorization_details"] = json.dumps(
        scoped_params["authorization_details"]
    )
    scoped_params["grant_type"] = "client_credentials"
    scoped = _post_form(token_url, scoped_params, client_id, client_secret)

    return {
        "token": scoped["access_token"],
        "instanceUrl": host,
        "workspaceId": org_id,
        "dashboardId": dashboard_id,
    }


def lambda_handler(event, context):
    try:
        payload = fetch_dashboard_embed_token()
    except urllib.error.URLError as e:
        logger.error("Databricks token exchange failed: %s", e)
        return {
            "statusCode": 502,
            "headers": _HEADERS,
            "body": json.dumps({"error": "dashboard token exchange failed"}),
        }

    return {"statusCode": 200, "headers": _HEADERS, "body": json.dumps(payload)}
