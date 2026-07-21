# Making `payment.py` Production Ready

Concrete change list, ordered by how badly it'll hurt you if skipped.

## Critical — money correctness & security

1. **Replace the in-memory dicts with a real DB.** `_processed_webhook_events` and `_order_creation_cache` need to be SQLite/Postgres tables (or Redis) with a unique constraint on the key. As plain dicts they don't survive a restart and don't work across multiple worker processes — meaning idempotency silently breaks under real traffic.

2. **Never trust `amount` from the request body.** In `create_payment`, `amount_rupees = str(body.get("amount", "20.00"))` lets any caller set their own price. Look up the price server-side (by product/plan ID sent in the request) instead of accepting a raw amount.

3. **Stop doing currency math in float.** `int(round(float(amount_rupees) * 100))` can round wrong for some values. Use `Decimal`, or better — require the caller to pass paise as an int directly and validate it against your server-side price table.

4. **Fill in the webhook business logic and fix event-marking order.** `if event_type == "payment.captured": pass` is a stub. Once real logic goes there (update subscription, send confirmation), make sure `_processed_webhook_events[event_id]` is only written *after* that logic succeeds — right now if you add real work after the `pass` and it throws, you still want the event marked "not yet processed" so a retry can complete it. Wrap create-record-then-mark-done in a DB transaction, not two separate steps.

5. **Also handle `payment.failed` and `order.paid` events**, not just `payment.captured` — right now anything else is silently accepted and dropped (`200 received: true` with no action), which is correct behavior for unrecognized events but you likely want at minimum to log/handle failures so you can alert users or trigger dunning.

6. **Verify webhook signature on the *raw* bytes before any parsing** — you're already doing this correctly (`request.get_data()` before `get_json`), just flagging it because it's the single most common Razorpay webhook bug (parsing then re-serializing changes the byte string and breaks HMAC verification).

## High — infrastructure

7. **Don't run `app.run()`.** Deploy with `gunicorn -w 4 -b 0.0.0.0:5000 app:app` (or similar) behind nginx/a reverse proxy, with TLS termination. `debug=False` is already correctly set — good, don't change that.

8. **Remove `_start_server_in_background()` / the `if __name__` pipeline runner from the production entrypoint.** That's a great local test harness but shouldn't be what starts your prod process — your prod entrypoint should just be `app` for gunicorn to import, with the interactive pipeline kept as a separate dev/test script.

9. **Move secrets out of `.env` on disk** into your host's env-injection (Railway/Render/AWS Secrets Manager/etc.), especially `RAZORPAY_KEY_SECRET` and `RAZORPAY_WEBHOOK_SECRET`.

10. **Add structured logging** (even just Python `logging` to stdout, captured by your host) on every error branch — right now failures return a JSON body to the caller but leave no trace anywhere for you to debug later. At minimum log: webhook signature failures, capture failures, and any 502/503 from Razorpay.

## Medium — robustness

11. **Rate-limit `/api/payment/create` and `/api/razorpay/webhook`.** Nothing currently stops abuse or a retry storm from Razorpay's side from hammering your endpoints.

12. **Add a request size limit** (`MAX_CONTENT_LENGTH` on the Flask app) so a malformed/huge webhook body can't be used to exhaust memory.

13. **Add a reconciliation job.** A periodic task (cron / Celery beat) that polls `/payments/{id}` for anything stuck `created`/`authorized` past a threshold, as a backstop in case a webhook never arrives.

14. **Validate `currency` against an allowlist** (`INR` only, unless you actually support multi-currency) rather than accepting whatever string the client sends.

## Nice-to-have

15. Add an idempotency check to `/api/payment/verify` too — right now a client could call it repeatedly; harmless since it's read-mostly, but worth a rate limit.
16. Add `/healthz` for your process supervisor/load balancer.

---

The one item on this list that actually requires code changes rather than deployment/config changes — and the highest-leverage one to get right before anything else here matters — is rewriting the storage layer to use SQLite with proper tables for both stores.
