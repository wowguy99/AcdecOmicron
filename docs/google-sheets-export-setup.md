# Google Sheet Text-Only Export — Setup Guide

This guide walks through enabling **Google Sheet** export for validated **Text-Only (track A)** cards. **Master** exports always remain CSV downloads.

## Cost

Google Sheets and Drive APIs are **free within normal quotas** for this app (~2 API calls per export). You may need to link a billing account to a Google Cloud project to enable APIs; typical personal use should not incur charges. See [Cost notes](#cost-notes) below.

---

## Part 1: Google Cloud (one-time)

### 1. Create a project

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project or select an existing one.

### 2. Enable APIs

1. Go to **APIs & Services → Library**.
2. Enable:
   - **Google Sheets API**
   - **Google Drive API** (required for the `drive.file` scope when creating spreadsheets)

### 3. Configure the OAuth consent screen

1. Go to **APIs & Services → OAuth consent screen**.
2. Choose **External** (fine for personal or small-team use).
3. Fill in required fields (app name, support email, etc.).
4. Scopes do not need to be added manually here — the app requests them at sign-in:
   - Google Sheets
   - Google Drive (`drive.file`)
5. Under **Test users**, add every Google account that will sign in (required while the app is in **Testing** mode).
6. Save.

### 4. Create an OAuth client ID

1. Go to **APIs & Services → Credentials → Create credentials → OAuth client ID**.
2. Application type: **Desktop app** (the backend uses a desktop OAuth flow with PKCE; no client secret is required).
3. Create the client and copy the **Client ID** (format: `123456789-xxxx.apps.googleusercontent.com`).

### 5. Set the redirect URI

The app uses this exact callback URL (default port **8000**):

```
http://127.0.0.1:8000/api/auth/google/callback
```

- Add this URI to the OAuth client if the console allows it.
- Use **`127.0.0.1`**, not `localhost`, unless you also register a `localhost` URI — the app hardcodes `127.0.0.1`.
- If you run the server on a different port, set the `PORT` environment variable and use that port in the redirect URI instead.

---

## Part 2: App prerequisites

### Install backend dependencies

From the repo root:

```powershell
python -m pip install -r backend/requirements.txt
```

This installs `google-auth`, `google-auth-oauthlib`, and `google-api-python-client`.

### Build the frontend (if needed)

```powershell
cd frontend
npm install
npm run build
cd ..
```

### Start the server

Run the app (e.g. `run.bat` or `run.ps1`) and open:

```
http://127.0.0.1:8000
```

**The server must be running** when you click **Connect Google account** — the OAuth callback is handled by your local FastAPI server.

---

## Part 3: Configure in Settings

1. Open the app → **Settings**.
2. Find **Text-Only export**.
3. Set **Format** to **Google Sheet (new sheet each export)**.
4. Paste your **Google OAuth client ID**.
5. Click **Save** (main Save button).

   **Important:** Save before connecting. **Connect Google account** reads the client ID from saved config on disk; unsaved values are not used.

6. Click **Connect Google account**.
   - A browser tab opens for Google sign-in.
   - Approve access.
   - You should see **“Google account connected”** in the browser.
7. Return to Settings and refresh — status should show **Connected**.

### Alternative: environment variable

Instead of pasting the client ID in Settings, you can set:

```
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
```

before starting the server.

### Where credentials are stored

- **Client ID** — saved in local config (`backend/data/config.json`, or `%LOCALAPPDATA%\AcDecFlashcards\` for the packaged installer).
- **Refresh token** — saved in the same file after sign-in; never shown in the UI.

---

## Part 4: Export Text-Only cards

1. Generate cards and **validate** the node you want (same rules as CSV download).
2. In the subject tree, click **Text-Only** on a subject, section, or subheader.
3. The app creates a **new** Google Sheet (title matches the CSV filename without `.csv`) and opens it in your browser.

Sheet layout matches CSV: three columns **Front**, **Back**, **Tag**, with **no header row**.

---

## Troubleshooting

| Issue | What to check |
|--------|----------------|
| “Google OAuth client ID is not configured” | Save Settings with the client ID filled in, or set `GOOGLE_CLIENT_ID`. |
| “OAuth session expired” | Complete sign-in within ~10 minutes of clicking Connect; try again. |
| “Google did not return a refresh token” | Click **Disconnect**, then **Connect** again. |
| Google “Access blocked” / app not verified | Add your account as a **Test user** on the OAuth consent screen. |
| Redirect URI mismatch | URI must exactly match `http://127.0.0.1:8000/api/auth/google/callback` (or your custom port). |
| 401 on export | Settings should show **Connected**; reconnect if needed. |
| 403 on export | Node or subject must be **validated** (same as CSV download). |
| Popup blocked | Allow popups for `127.0.0.1:8000` so the sign-in tab can open. |

---

## Cost notes

- **API usage:** Creating and filling a sheet uses about two API calls per export — well within the free tier for personal use.
- **Billing account:** Google may require a billing account on the Cloud project to enable APIs; you typically pay **$0** unless you exceed free quotas or use paid services.
- **OAuth verification:** For yourself and a few test users, **Testing** mode is enough. Distributing to many unrelated users may require Google OAuth app verification (compliance review, not a per-export fee).
- **Distribution:** You can use **one** Google Cloud project and embed a single Client ID in a shipped build so end users only click **Connect Google account** — they do not need their own Cloud project.

---

## Quick checklist

- [ ] Google Sheets API and Drive API enabled
- [ ] OAuth consent screen configured; test users added
- [ ] Desktop OAuth client created; Client ID copied
- [ ] Redirect URI `http://127.0.0.1:8000/api/auth/google/callback` registered
- [ ] App running on port 8000
- [ ] Settings: Google Sheet format + Client ID **saved**
- [ ] Connect Google → success page → **Connected**
- [ ] Validated Text-Only export opens a new sheet
