# xero-backup

A set of Python scripts to do a complete backup of your Xero account — including all accounting data, invoice PDFs, and scanned receipts/attachments.

Xero has no built-in "export everything" button. These scripts use the Xero API to pull everything down automatically, then reformat it into a human-browsable folder structure.

**What you end up with:**
- All invoices, bills, bank transactions, contacts, payments, and manual journals as JSON
- Every invoice as a PDF
- All attached receipts and scanned documents, renamed with dates and contact names
- A combined `transactions.csv` covering everything (easy to open in Excel)
- A `summary.xlsx` workbook with separate tabs for invoices, bills, bank transactions, and contacts

---

## Requirements

- Python 3 (see Step 1 if you're not sure whether you have it)
- A Xero account with Owner or Administrator access
- About 10 minutes of setup, then the scripts run unattended

---

## Step 1 — Check Python is installed

Open Terminal and run:

```
python3 --version
```

If it prints a version number (e.g. `Python 3.9.6`), you're good. If you get "command not found", download and install Python from [python.org](https://www.python.org/downloads/) first.

---

## Step 2 — Download these scripts

Download all four `.py` files into a folder on your computer (e.g. `~/xero-backup/`). Make sure they're all in the same folder.

---

## Step 3 — Install dependencies

In Terminal:

```
pip3 install requests pyopenssl openpyxl
```

If `pip3` isn't found, try `pip` instead.

---

## Step 4 — Set up a Xero Developer app

This is the main setup step. You need to register a free "app" with Xero so the scripts can authenticate with your account.

**4a.** Go to [developer.xero.com](https://developer.xero.com) and sign in with your normal Xero credentials (same login — no new account needed).

**4b.** Click **My Apps** in the top navigation, then **New App**.

Fill in:
- **App name:** anything you like, e.g. `My Backup Script`
- **Integration type:** Web App
- **Company or application URL:** `https://localhost`
- **Privacy policy URL:** leave blank
- **Terms and conditions URL:** leave blank

Click **Create App**.

**4c.** In the left sidebar, click **Configuration**. Set the **Redirect URI** to:

```
https://localhost:8080/callback
```

Click **Save**.

> **Note:** Xero requires `https://` even for localhost. Don't use `http://`.

**4d.** Still on the Configuration page, you should now see your **Client ID**. Click **Generate a secret** to create your **Client Secret**. Copy both — you'll need them in the next step.

> If you don't see Client ID immediately after saving, try refreshing the page.

---

## Step 5 — Generate a local TLS certificate

Because Xero requires `https://` for the redirect URI, the scripts need a self-signed certificate to run a local HTTPS server during login. This is only used on your own machine.

In Terminal, `cd` to the folder containing the scripts, then run:

```
cd ~/xero-backup
python3 1_generate_cert.py
```

This creates `cert.pem` and `key.pem` in the same folder. You should see:

```
Created cert.pem and key.pem
```

> Make sure you run this from inside the scripts folder — the cert files need to be in the same place as the other scripts.

---

## Step 6 — Log in to Xero (one-time)

Open `2_login.py` in a text editor and fill in your Client ID and Client Secret from Step 4d:

```python
CLIENT_ID = "paste your client ID here"
CLIENT_SECRET = "paste your client secret here"
```

Save the file, then run it:

```
python3 2_login.py
```

This will:
1. Open your browser to Xero's login/consent page
2. You log in and click **Allow Access**
3. Your browser will redirect to `https://localhost:8080/callback` and show a "Success!" message — this is expected
4. The script saves `tokens.json` and `tenants.json` in the scripts folder

> **Browser security warning:** When the browser redirects to localhost, it may show a "your connection is not private" or "Safari can't verify the identity" warning. This is expected — the certificate is self-signed and only used on your own machine. Click **Advanced** → **Proceed to localhost** (Chrome) or **Visit Website** (Safari) to continue.

> **If the browser shows "can't connect to server":** The local server wasn't running when the browser arrived. This usually means the script errored before starting. Check the terminal for errors, make sure `cert.pem` and `key.pem` are in the same folder as the scripts, and try again.

At the end, the script will print your connected Xero organisation name. If you have multiple organisations, you'll be asked to choose one when you run the backup.

---

## Step 7 — Run the backup

```
python3 3_backup.py
```

This will work through:
- All invoices, bills, contacts, bank transactions, manual journals, payments (saved as JSON)
- All invoice PDFs
- All attachments on invoices, bills, bank transactions, and contacts (receipts, scans, etc.)
- Files uploaded to Xero's Files inbox

Progress is printed as it goes. **It's safe to stop and restart at any time** — the script skips anything already downloaded, so it resumes where it left off.

Output goes into a `xero_backup/` folder in the scripts directory.

### Rate limits

Xero allows 60 API calls per minute and 5,000 per day. The script handles this automatically — it paces itself and will stop with a clear message if the daily limit is reached. Just run `python3 3_backup.py` again the next day and it will continue.

For a large account with many years of data and lots of receipts, expect this to take 2–3 days of evening runs to complete. Each run makes meaningful progress before hitting the daily cap.

---

## Step 8 — Reformat into a human-browsable structure

Once the backup has finished (or even partway through), run:

```
python3 4_reformat.py
```

This creates a separate `xero_backup_organised/` folder containing:

```
xero_backup_organised/
  files/
    invoices/         Invoice PDFs + attachments, named: YYYY-MM-DD_Contact_Invoice_INV-XXXX.pdf
    bills/            Bill PDFs + attachments
    bank_transactions/ Receipt scans, named: YYYY-MM-DD_Contact_SPEND_RECEIPT_filename.pdf
    contacts/         Contact attachments
  transactions.csv    Every transaction as flat line-item rows (open in Excel)
  summary.xlsx        Four-tab workbook: Invoices, Bills, Bank Transactions, Contacts
```

Your original `xero_backup/` folder is left completely untouched. You can re-run `4_reformat.py` at any time — for example, after resuming `3_backup.py` the next day to pick up more data.

---

## Files generated (don't commit these to git)

| File | Contents |
|------|----------|
| `tokens.json` | Xero OAuth tokens — treat like a password |
| `tenants.json` | Your Xero organisation ID |
| `cert.pem` / `key.pem` | Local TLS certificate |
| `xero_backup/` | All downloaded data |
| `xero_backup_organised/` | Reformatted output |

If you're putting these scripts on GitHub, make sure none of the above are included. A `.gitignore` is included in this repo to prevent that.

---

## Troubleshooting

**`pip3: command not found`**
Try `pip` instead of `pip3`. If neither works, Python may not be installed — see Step 1.

**`python3: can't open file '1_generate_cert.py': No such file or directory`**
You're not in the right folder. Use `cd` to navigate to where you saved the scripts first, e.g. `cd ~/xero-backup`.

**`Error: invalid_scope` when logging in**
The scope names Xero supports depend on when your app was created. The scripts use the current granular scope names (post-March 2026). If you created your app before that date and are getting this error, check your app's Configuration page in the Xero Developer portal — the available scopes are listed there.

**`FileNotFoundError: cert.pem`**
The cert files aren't in the same folder as the scripts. Make sure you ran `1_generate_cert.py` from inside the scripts folder (not your home directory), and that `cert.pem` and `key.pem` appear alongside the `.py` files.

**`Hit 429, waiting 25000s...` (script sleeping for hours)**
This was a bug in early versions of the script where an absurdly large `Retry-After` value from Xero was obeyed literally. The current version detects this and stops cleanly instead. Make sure you have the latest `3_backup.py`.

**Script stops with "daily quota" message**
Normal — Xero's 5,000 calls/day limit has been reached. Just re-run `python3 3_backup.py` the following day.

**Token expired / login needed again**
If you haven't run the backup in 60+ days, the refresh token may have expired. Just re-run `python3 2_login.py` to log in again (you won't lose any downloaded data).

---

## Notes

- Payroll data is not included (requires separate Xero Payroll API scopes and a different endpoint structure)
- Credit notes and purchase orders are not available as API scopes for apps created after March 2026
- The scripts are read-only — they never write anything back to your Xero account
