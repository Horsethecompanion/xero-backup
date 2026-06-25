"""
Step 3: Full backup of Xero data.

Uses the refresh token from tokens.json (produced by 2_login.py) to pull:
  - Contacts, Invoices, Bills, Credit Notes, Bank Transactions,
    Manual Journals, Accounts, Payments (as JSON)
  - Invoice PDFs
  - All attachments on the above records (receipts, scanned docs)
  - Files API inbox (uploaded but unattached files)

Output structure:
  xero_backup/
    data/            <- raw JSON for each endpoint
    invoice_pdfs/
    attachments/      <- organised by record type / record number
    files_inbox/

Handles:
  - automatic access token refresh (tokens expire every 30 min)
  - basic rate limiting (60 calls/min, 5000/day)
  - pagination

Run: python 3_backup.py
"""

import json
import os
import time
from pathlib import Path

import requests

BASE = "https://api.xero.com/api.xro/2.0"
FILES_BASE = "https://api.xero.com/files.xro/1.0"
TOKEN_URL = "https://identity.xero.com/connect/token"

OUT_DIR = Path("xero_backup")
DATA_DIR = OUT_DIR / "data"
PDF_DIR = OUT_DIR / "invoice_pdfs"
ATTACH_DIR = OUT_DIR / "attachments"
FILES_DIR = OUT_DIR / "files_inbox"

for d in (DATA_DIR, PDF_DIR, ATTACH_DIR, FILES_DIR):
    d.mkdir(parents=True, exist_ok=True)

CALLS_THIS_MINUTE = 0
MINUTE_WINDOW_START = time.time()
TOTAL_CALLS_TODAY = 0


def load_tokens():
    with open("tokens.json") as f:
        return json.load(f)


def save_tokens(tokens):
    with open("tokens.json", "w") as f:
        json.dump(tokens, f, indent=2)


def refresh_access_token(tokens):
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
        },
        auth=(tokens["client_id"], tokens["client_secret"]),
    )
    resp.raise_for_status()
    new_tokens = resp.json()
    tokens["access_token"] = new_tokens["access_token"]
    tokens["refresh_token"] = new_tokens["refresh_token"]
    tokens["expires_at"] = time.time() + new_tokens["expires_in"] - 60
    save_tokens(tokens)
    return tokens


def get_tenant_id():
    with open("tenants.json") as f:
        tenants = json.load(f)
    if len(tenants) == 1:
        return tenants[0]["tenantId"], tenants[0]["tenantName"]
    print("Multiple organisations connected:")
    for i, t in enumerate(tenants):
        print(f"  [{i}] {t['tenantName']}")
    idx = int(input("Which one do you want to back up? Enter number: "))
    return tenants[idx]["tenantId"], tenants[idx]["tenantName"]


tokens = load_tokens()
tenant_id, tenant_name = get_tenant_id()
print(f"Backing up: {tenant_name}\n")


def throttle():
    """Keep us under 60 calls/min."""
    global CALLS_THIS_MINUTE, MINUTE_WINDOW_START, TOTAL_CALLS_TODAY
    now = time.time()
    if now - MINUTE_WINDOW_START > 60:
        MINUTE_WINDOW_START = now
        CALLS_THIS_MINUTE = 0
    if CALLS_THIS_MINUTE >= 55:  # leave headroom
        sleep_time = 60 - (now - MINUTE_WINDOW_START) + 1
        print(f"  (rate limit pacing: sleeping {sleep_time:.0f}s)")
        time.sleep(max(sleep_time, 0))
        MINUTE_WINDOW_START = time.time()
        CALLS_THIS_MINUTE = 0
    CALLS_THIS_MINUTE += 1
    TOTAL_CALLS_TODAY += 1
    if TOTAL_CALLS_TODAY >= 4900:
        print("\nApproaching the 5000 calls/day limit.")
        print("Stop here, wait until tomorrow (resets midnight UTC), and re-run this script.")
        print("It's safe to re-run -- already-downloaded files won't be re-fetched.")
        raise SystemExit(1)


def api_get(url, params=None, headers_extra=None, raw=False):
    """GET with auto token refresh and rate limiting."""
    global tokens
    if time.time() > tokens.get("expires_at", 0):
        print("  Refreshing access token...")
        tokens = refresh_access_token(tokens)

    throttle()
    headers = {
        "Authorization": f"Bearer {tokens['access_token']}",
        "Xero-tenant-id": tenant_id,
        "Accept": "application/json" if not raw else "*/*",
    }
    if headers_extra:
        headers.update(headers_extra)

    resp = requests.get(url, headers=headers, params=params)

    if resp.status_code == 401:
        print("  Token expired mid-run, refreshing...")
        tokens = refresh_access_token(tokens)
        headers["Authorization"] = f"Bearer {tokens['access_token']}"
        resp = requests.get(url, headers=headers, params=params)

    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 60))
        if retry_after > 120:
            # Xero sometimes returns a daily-quota reset time here rather
            # than a short per-minute throttle. Don't block silently for
            # hours -- stop and let the person decide.
            print(f"\nGot a 429 with Retry-After={retry_after}s (over 2 min).")
            print("This usually means the daily API call quota (5000/day) has been hit,")
            print("not just the per-minute rate limit.")
            print("Stop here and re-run this script later (e.g. after midnight UTC,")
            print("when the daily quota resets). It's safe to re-run -- already")
            print("downloaded files won't be re-fetched.")
            raise SystemExit(1)
        print(f"  Hit 429, waiting {retry_after}s...")
        time.sleep(retry_after + 1)
        return api_get(url, params, headers_extra, raw)

    resp.raise_for_status()
    return resp if raw else resp.json()


def safe_name(s):
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in str(s))[:120]


# ---------------------------------------------------------------------------
# 1. Pull all core accounting endpoints as JSON (paginated where applicable)
# ---------------------------------------------------------------------------

PAGINATED_ENDPOINTS = [
    "Invoices",
    "Contacts",
    "BankTransactions",
    "ManualJournals",
    "Payments",
]

NON_PAGINATED_ENDPOINTS = [
    "Accounts",
    "TaxRates",
    "TrackingCategories",
    "Currencies",
    "Organisation",
    "BankTransfers",
    "Journals",  # uses offset, not page -- handled specially below
]


def fetch_paginated(endpoint):
    out_file = DATA_DIR / f"{endpoint}.json"
    if out_file.exists():
        print(f"[skip] {endpoint} already downloaded")
        with open(out_file) as f:
            return json.load(f)

    print(f"Fetching {endpoint}...")
    all_records = []
    page = 1
    key = endpoint  # Xero returns e.g. {"Invoices": [...]}
    while True:
        data = api_get(f"{BASE}/{endpoint}", params={"page": page, "pageSize": 100})
        records = data.get(key, [])
        if not records:
            break
        all_records.extend(records)
        print(f"  page {page}: {len(records)} records (total {len(all_records)})")
        if len(records) < 100:
            break
        page += 1

    with open(out_file, "w") as f:
        json.dump(all_records, f, indent=2)
    print(f"  -> saved {len(all_records)} {endpoint} to {out_file}")
    return all_records


def fetch_journals():
    out_file = DATA_DIR / "Journals.json"
    if out_file.exists():
        print("[skip] Journals already downloaded")
        with open(out_file) as f:
            return json.load(f)

    print("Fetching Journals...")
    all_records = []
    offset = 0
    while True:
        data = api_get(f"{BASE}/Journals", params={"offset": offset})
        records = data.get("Journals", [])
        if not records:
            break
        all_records.extend(records)
        print(f"  offset {offset}: {len(records)} records (total {len(all_records)})")
        offset = records[-1]["JournalNumber"]
        if len(records) < 100:
            break

    with open(out_file, "w") as f:
        json.dump(all_records, f, indent=2)
    print(f"  -> saved {len(all_records)} Journals to {out_file}")
    return all_records


def fetch_simple(endpoint):
    out_file = DATA_DIR / f"{endpoint}.json"
    if out_file.exists():
        print(f"[skip] {endpoint} already downloaded")
        with open(out_file) as f:
            return json.load(f)

    print(f"Fetching {endpoint}...")
    data = api_get(f"{BASE}/{endpoint}")
    with open(out_file, "w") as f:
        json.dump(data, f, indent=2)
    key = endpoint
    n = len(data.get(key, [])) if isinstance(data.get(key), list) else 1
    print(f"  -> saved {endpoint} ({n} records) to {out_file}")
    return data


# ---------------------------------------------------------------------------
# 2. Download invoice PDFs
# ---------------------------------------------------------------------------

def download_invoice_pdfs(invoices):
    print(f"\nDownloading {len(invoices)} invoice PDFs...")
    for i, inv in enumerate(invoices):
        inv_id = inv["InvoiceID"]
        inv_number = inv.get("InvoiceNumber", inv_id)
        out_path = PDF_DIR / f"{safe_name(inv_number)}.pdf"
        if out_path.exists():
            continue
        try:
            resp = api_get(
                f"{BASE}/Invoices/{inv_id}",
                headers_extra={"Accept": "application/pdf"},
                raw=True,
            )
            out_path.write_bytes(resp.content)
        except Exception as e:
            print(f"  WARN: failed PDF for invoice {inv_number}: {e}")
        if (i + 1) % 25 == 0:
            print(f"  ...{i + 1}/{len(invoices)} PDFs done")
    print(f"  -> {len(list(PDF_DIR.glob('*.pdf')))} PDFs in {PDF_DIR}")


# ---------------------------------------------------------------------------
# 3. Download attachments for any record type that has them
# ---------------------------------------------------------------------------

ATTACHMENT_SOURCES = [
    # (endpoint name for attachments URL, id field, list, human label, number field)
    ("Invoices", "InvoiceID", "InvoiceNumber"),
    ("BankTransactions", "BankTransactionID", "BankTransactionID"),
    ("Contacts", "ContactID", "Name"),
]


def download_attachments_for(endpoint, id_field, number_field, records):
    folder = ATTACH_DIR / endpoint
    folder.mkdir(exist_ok=True)
    print(f"\nChecking attachments on {len(records)} {endpoint}...")
    found_total = 0
    for i, rec in enumerate(records):
        if not rec.get("HasAttachments"):
            continue
        rec_id = rec[id_field]
        rec_label = safe_name(rec.get(number_field, rec_id))

        # If we already have at least one file for this record on disk,
        # assume it's fully downloaded and skip the list call entirely.
        # (Saves a call per record on resumed runs -- the main quota cost.)
        existing = list(folder.glob(f"{rec_label}__*"))
        if existing:
            found_total += len(existing)
            continue

        try:
            data = api_get(f"{BASE}/{endpoint}/{rec_id}/Attachments")
        except Exception as e:
            print(f"  WARN: couldn't list attachments for {rec_label}: {e}")
            continue
        atts = data.get("Attachments", [])
        for att in atts:
            found_total += 1
            att_name = safe_name(att["FileName"])
            out_path = folder / f"{rec_label}__{att_name}"
            if out_path.exists():
                continue
            try:
                resp = api_get(
                    f"{BASE}/{endpoint}/{rec_id}/Attachments/{att['AttachmentID']}",
                    headers_extra={"Accept": att.get("MimeType", "*/*")},
                    raw=True,
                )
                out_path.write_bytes(resp.content)
            except Exception as e:
                print(f"  WARN: failed attachment {att_name} on {rec_label}: {e}")
        if (i + 1) % 50 == 0:
            print(f"  ...{i + 1}/{len(records)} {endpoint} checked, {found_total} attachments so far")
    print(f"  -> done with {endpoint}: {found_total} attachments found")


# ---------------------------------------------------------------------------
# 4. Files API inbox (files uploaded to Xero but not necessarily attached
#    to a specific transaction)
# ---------------------------------------------------------------------------

def download_files_inbox():
    print("\nFetching Files API inbox...")
    page = 1
    all_files = []
    while True:
        data = api_get(f"{FILES_BASE}/Files", params={"pagesize": 100, "page": page})
        items = data.get("Items", [])
        if not items:
            break
        all_files.extend(items)
        if len(items) < 100:
            break
        page += 1

    with open(DATA_DIR / "FilesInbox.json", "w") as f:
        json.dump(all_files, f, indent=2)
    print(f"  Found {len(all_files)} files in Files API")

    for i, file_meta in enumerate(all_files):
        file_id = file_meta["Id"]
        name = safe_name(file_meta.get("Name", file_id))
        out_path = FILES_DIR / name
        if out_path.exists():
            continue
        try:
            resp = api_get(f"{FILES_BASE}/Files/{file_id}/Content", raw=True)
            out_path.write_bytes(resp.content)
        except Exception as e:
            print(f"  WARN: failed file {name}: {e}")
        if (i + 1) % 25 == 0:
            print(f"  ...{i + 1}/{len(all_files)} files downloaded")
    print(f"  -> {len(list(FILES_DIR.glob('*')))} files in {FILES_DIR}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Core JSON data
    invoices = fetch_paginated("Invoices")
    contacts = fetch_paginated("Contacts")
    bank_transactions = fetch_paginated("BankTransactions")
    manual_journals = fetch_paginated("ManualJournals")
    payments = fetch_paginated("Payments")

    fetch_simple("Accounts")
    fetch_simple("Organisation")

    # PDFs
    download_invoice_pdfs(invoices)

    # Attachments
    download_attachments_for("Invoices", "InvoiceID", "InvoiceNumber", invoices)
    download_attachments_for("BankTransactions", "BankTransactionID", "BankTransactionID", bank_transactions)
    download_attachments_for("Contacts", "ContactID", "Name", contacts)

    # Files inbox
    download_files_inbox()

    print("\n" + "=" * 60)
    print("BACKUP COMPLETE")
    print(f"Output folder: {OUT_DIR.resolve()}")
    print("=" * 60)


if __name__ == "__main__":
    main()
