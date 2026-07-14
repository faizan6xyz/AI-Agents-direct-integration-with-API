# Master Guide: API Integration, Meta Graph API, and Backend Deployment

## Table of Contents
1. [Architecture: Managing APIs Without Republishing](#1-architecture-managing-apis-without-republishing)
2. [Payments: PayPal & UPI/QR Code Limitations](#2-payments-paypal--upiqr-code-limitations)
3. [Backend: Deploying Flask (and FastAPI)](#3-backend-deploying-flask-and-fastapi)
4. [Instagram API: Engagement Limits & Media IDs](#4-instagram-api-engagement-limits--media-ids)
5. [Instagram API: Polling for Likes (Python Code)](#5-instagram-api-polling-for-likes-python-code)
6. [Webhooks: Instagram, WhatsApp, and Gmail](#6-webhooks-instagram-whatsapp-and-gmail)

---

## 1. Architecture: Managing APIs Without Republishing
To avoid republishing your core application every time a third-party API changes, you must decouple your app from external services.

* **Environment Variables & Secret Managers:** Never hardcode API keys or URLs. Store them in `.env` files or services like AWS Secrets Manager. Update them in your hosting dashboard without touching code.
* **Backend-for-Frontend (BFF) / Middleware:** Build a lightweight internal API. Your frontend talks only to your backend; your backend handles the messy 3rd-party API integrations.
* **Adapter Pattern:** Create interfaces for external APIs. If Company A changes their payload, you only update the Adapter file, not your core business logic.
* **iPaaS (No-Code):** Use tools like n8n, Make, or Zapier to connect APIs visually. If an API updates, you tweak the workflow on their platform, not your codebase.
* **API Gateways:** Use Kong, AWS API Gateway, or Cloudflare Workers to handle routing, CORS, and authentication injection at the edge.
* **CI/CD:** Automate deployments using GitHub Actions or Vercel so "publishing" happens automatically on git push.

---

## 2. Payments: PayPal & UPI/QR Code Limitations
**PayPal cannot directly accept UPI payments or generate interoperable UPI QR codes.**

* **Direct UPI to PayPal:** Not supported. PayPal India does not function as a UPI merchant aggregator.
* **PayPal QR Codes:** These are PayPal-exclusive. Scanning them with GPay/PhonePe will fail; the sender must use the PayPal app.
* **The "PayPal + UPI" News:** This integration only allows Indian users to *fund outgoing international payments* using UPI. It does not allow merchants to *receive* local UPI payments.
* **Solution:** Use Razorpay, Cashfree, or PhonePe Business for local UPI/QR codes. Keep PayPal strictly for international credit card/invoice payments.

---

## 3. Backend: Deploying Flask (and FastAPI)
Flask is excellent for deployment, but it is a framework, not a web server.

* **The Golden Rule:** Never use `flask run` or `app.run()` in production. 
* **The Production Stack:** Use a WSGI server like **Gunicorn** or **uWSGI**, ideally behind a reverse proxy like **Nginx**.
* **Deployment Paths:**
  * *PaaS (Easy):* Render, Railway, Heroku. Just add a `Procfile` (`web: gunicorn app:app`).
  * *VPS (Standard):* Docker + Gunicorn + Nginx on AWS EC2 / DigitalOcean.
  * *Serverless:* AWS Lambda or Google Cloud Run (requires adapting for cold starts).
* **Alternative:** Consider **FastAPI** if you are building an API router. It is asynchronous (faster for multiple external API calls) and auto-generates documentation.

---

## 4. Instagram API: Engagement Limits & Media IDs
The Meta Graph API strictly limits what data you can extract due to privacy rules.

### What you CANNOT get (User IDs):
* **Views/Watched:** Only aggregate `play_count` or `impressions`.
* **Likes:** Only aggregate `like_count`. No list of users.
* **Shares:** Only aggregate `shared_count`.

### What you CAN get:
* **Comments:** You can get the `id` and `username` of everyone who comments via `GET /{ig-media-id}/comments`.
* **Prerequisites:** Requires an IG Business/Creator account linked to a Facebook Page, and a Meta Developer App with `instagram_basic` and `pages_read_engagement` permissions.

### Fetching Media IDs and Captions
The API only returns data you explicitly ask for in the `fields` parameter. 

**Endpoint to get all media (Reels & Posts):**
```http
GET https://graph.facebook.com/v20.0/{YOUR_IG_USER_ID}/media?fields=id,caption,media_type,media_product_type,permalink&access_token=YOUR_TOKEN