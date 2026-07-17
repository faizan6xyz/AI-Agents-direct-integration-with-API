# Environment Variables Reference — WhatsApp, Instagram, Gmail

## WhatsApp Business Cloud API

| Variable | Example | Purpose |
|---|---|---|
| `WHATSAPP_ACCESS_TOKEN` | `EAAGm0PX4ZCpsBO...` (long string) | Bearer token sent in the `Authorization` header on every Graph API call (sending messages, downloading media). Temporary tokens expire in 24h; System User tokens can be permanent. |
| `WHATSAPP_PHONE_NUMBER_ID` | `109876543210987` | The ID of *your* business phone number in Meta's system (not the actual phone number). Used in the URL path when sending messages: `/v20.0/{PHONE_NUMBER_ID}/messages`. |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | `987654321098765` | The WABA (WhatsApp Business Account) ID — the parent account that can own multiple phone numbers. Needed for account-level API calls (e.g. listing templates). |
| `WHATSAPP_VERIFY_TOKEN` | `my_super_secret_verify_2026` | A string *you* invent. Meta sends it back to your `/webhook` GET endpoint during setup — you check it matches before confirming the webhook subscription. |
| `WHATSAPP_APP_SECRET` | `a1b2c3d4e5f6...` (32-char hex) | Used to compute the HMAC-SHA256 signature for verifying `X-Hub-Signature-256` — confirms incoming webhook payloads genuinely came from Meta and weren't spoofed. |
| `WHATSAPP_API_VERSION` | `v20.0` | Graph API version string used in every request URL. Meta deprecates old versions periodically, so this stays configurable rather than hardcoded. |

## Instagram (Meta Graph API)

| Variable | Example | Purpose |
|---|---|---|
| `INSTAGRAM_ACCESS_TOKEN` | `IGQVJYb...` | Token for calling Instagram Graph API endpoints (reading DMs, comments, posting). |
| `INSTAGRAM_BUSINESS_ACCOUNT_ID` | `17841400000000000` | The Instagram Business/Creator account ID linked to your Facebook Page — required in API paths like `/{IG_ACCOUNT_ID}/media`. |
| `INSTAGRAM_APP_ID` | `1234567890123456` | Your Meta App's ID — used in OAuth authorization URLs (`?client_id={APP_ID}`). |
| `INSTAGRAM_APP_SECRET` | `9f8e7d6c5b4a...` | Used both for OAuth token exchange and for verifying webhook signatures, same mechanism as WhatsApp's app secret. |
| `INSTAGRAM_VERIFY_TOKEN` | `my_ig_verify_2026` | Same idea as WhatsApp's verify token — a string you pick that Meta echoes back during webhook subscription setup. |
| `INSTAGRAM_REDIRECT_URI` | `https://yourdomain.com/auth/instagram/callback` | Where Meta redirects the user after they approve OAuth permissions — must exactly match what's registered in the Meta App dashboard. |

## Gmail (Google OAuth2)

| Variable | Example | Purpose |
|---|---|---|
| `GMAIL_CLIENT_ID` | `123456-abc.apps.googleusercontent.com` | Public identifier for your app registered in Google Cloud Console — used to start the OAuth consent flow. |
| `GMAIL_CLIENT_SECRET` | `GOCSPX-aBcDeFgH...` | Secret paired with the client ID, used when exchanging an authorization code (or refresh token) for an access token. |
| `GMAIL_REDIRECT_URI` | `https://yourdomain.com/auth/google/callback` | Where Google sends the user back with an auth code after consent — must match a URI registered in Cloud Console exactly. |
| `GMAIL_REFRESH_TOKEN` | `1//0gAbCdEfGhIj...` | Long-lived credential obtained once after the user consents. Your app uses this to silently mint new short-lived access tokens without asking the user to log in again. |
| `GMAIL_TOKEN_URI` | `https://oauth2.googleapis.com/token` | The Google endpoint you POST to (with client ID/secret/refresh token) to get a fresh access token. Rarely changes — it's Google's fixed token endpoint. |
| `GMAIL_SCOPES` | `https://www.googleapis.com/auth/gmail.readonly,...send` | Comma-separated list of permissions your app requests — determines what your app is allowed to do (read-only inbox access vs. sending mail vs. full access). |

## Shared App Config

| Variable | Example | Purpose |
|---|---|---|
| `FLASK_ENV` | `development` or `production` | Toggles Flask's debug mode, error verbosity, and auto-reload — never `development` in prod. |
| `FLASK_SECRET_KEY` | `8f4a2b1c9d3e...` (random 32+ byte string) | Signs session cookies / CSRF tokens. Should be a long random value, generated once via `secrets.token_hex(32)`. |
| `BASE_URL` | `https://yourdomain.com` | Your app's public URL — used to construct redirect URIs and webhook callback URLs dynamically instead of hardcoding them everywhere. |

## Security Notes

- `WHATSAPP_ACCESS_TOKEN` / `INSTAGRAM_ACCESS_TOKEN` and the two app secrets need real rotation discipline — if any of those leak, someone can send messages or read data as your business.
- The verify tokens are lower-stakes since they're only used during the webhook handshake, not for ongoing auth.
- Never commit `.env` to version control — make sure it's in `.gitignore`, and keep an `.env.example` with blank/placeholder values in the repo instead.
