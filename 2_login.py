"""
Step 2: One-time OAuth2 login to Xero.

This opens your browser to Xero's login/consent screen. After you log in
and approve, Xero redirects back to https://localhost:8080/callback,
which this script is listening on. It captures the authorization code,
exchanges it for an access token + refresh token, and saves them to
tokens.json for the backup script to use.

You only need to do this once. The refresh token can be used repeatedly
(re-run this script if it ever expires or is revoked).

BEFORE RUNNING:
1. Run 1_generate_cert.py first
2. Fill in CLIENT_ID and CLIENT_SECRET below
3. Run: python 2_login.py
"""

import json
import secrets
import ssl
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs

import requests

# ---- FILL THESE IN ----
CLIENT_ID = "YOUR_CLIENT_ID_HERE"
CLIENT_SECRET = "YOUR_CLIENT_SECRET_HERE"
# ------------------------

REDIRECT_URI = "https://localhost:8080/callback"
AUTH_URL = "https://login.xero.com/identity/connect/authorize"
TOKEN_URL = "https://identity.xero.com/connect/token"

SCOPES = (
    "openid profile email offline_access "
    "accounting.invoices.read accounting.banktransactions.read "
    "accounting.contacts.read accounting.attachments.read "
    "accounting.manualjournals.read accounting.settings.read "
    "accounting.payments.read files.read"
)
# Note: no scope for CreditNotes or PurchaseOrders exists in this app's
# scope list, so those record types/their attachments will be skipped
# in the backup script. Journals (system ledger) also unavailable.

state = secrets.token_urlsafe(16)
result = {}


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = parse_qs(parsed.query)
        returned_state = params.get("state", [None])[0]
        code = params.get("code", [None])[0]

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

        if returned_state != state or not code:
            self.wfile.write(b"<h1>Error: state mismatch or no code. You can close this tab.</h1>")
            result["error"] = "state mismatch or missing code"
        else:
            self.wfile.write(b"<h1>Success! You can close this tab and return to the script.</h1>")
            result["code"] = code

        threading.Thread(target=self.server.shutdown).start()

    def log_message(self, format, *args):
        pass  # silence default logging


def main():
    if "YOUR_CLIENT_ID_HERE" in CLIENT_ID:
        print("ERROR: Edit this file and fill in CLIENT_ID and CLIENT_SECRET first.")
        return

    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
    }
    auth_url = f"{AUTH_URL}?{urlencode(params)}"

    print("Opening browser for Xero login...")
    print(f"If it doesn't open automatically, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    server = HTTPServer(("localhost", 8080), CallbackHandler)
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")
    server.socket = ssl_context.wrap_socket(server.socket, server_side=True)
    print("Waiting for you to log in and authorise in the browser...")
    server.serve_forever()

    if "error" in result:
        print(f"Login failed: {result['error']}")
        return

    print("Got authorization code. Exchanging for tokens...")
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": result["code"],
            "redirect_uri": REDIRECT_URI,
        },
        auth=(CLIENT_ID, CLIENT_SECRET),
    )

    if resp.status_code != 200:
        print(f"Token exchange failed: {resp.status_code} {resp.text}")
        return

    tokens = resp.json()
    tokens["client_id"] = CLIENT_ID
    tokens["client_secret"] = CLIENT_SECRET

    with open("tokens.json", "w") as f:
        json.dump(tokens, f, indent=2)

    print("Saved tokens.json")

    # Fetch connected tenants (organisations) so the backup script knows the tenant ID
    conn_resp = requests.get(
        "https://api.xero.com/connections",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    tenants = conn_resp.json()
    print("\nConnected organisations:")
    for t in tenants:
        print(f"  - {t['tenantName']}  (tenantId: {t['tenantId']})")

    with open("tenants.json", "w") as f:
        json.dump(tenants, f, indent=2)

    print("\nSaved tenants.json. Next: run 3_backup.py")


if __name__ == "__main__":
    main()
