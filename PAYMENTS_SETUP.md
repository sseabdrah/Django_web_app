# Mobile Money Payments

The app supports Flutterwave Uganda Mobile Money charges for Airtel Money and MTN. It never requests or stores a Mobile Money PIN; customers approve the charge through Flutterwave and their mobile operator.

## Configure Flutterwave

1. Create and verify a Flutterwave merchant account and enable Uganda UGX Mobile Money charges. Test with Flutterwave test credentials first.
2. Set these environment variables on the application server. Do not commit the values or send them in chat.

   - `FLW_SECRET_KEY`: Flutterwave secret API key for the selected test/live mode.
   - `FLW_SECRET_HASH`: the webhook secret hash configured in the Flutterwave dashboard.

3. Configure the Flutterwave webhook URL as `https://YOUR_PUBLIC_DOMAIN/payments/flutterwave/webhook/`, use the same secret hash, and enable the `charge.completed` event and webhook retries.
4. Set a public HTTPS domain in Django `ALLOWED_HOSTS` and CSRF trusted origins as appropriate for deployment. The payment return URL is generated from the current request host.
5. Apply database changes with `python manage.py migrate`.

Checkout stays disabled unless both payment secrets are configured. A payment only grants access after the server verifies its transaction reference, successful status, UGX currency, and amount with Flutterwave. Webhook signatures are checked before processing, and duplicate events do not extend access twice.

## Admin Email Notifications

Verified payments appear in the custom admin dashboard and Payments page. The app also emails the configured `DIETAPP_ADMIN_EMAIL` when the email backend can deliver mail. For SMTP, configure the `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and `DEFAULT_FROM_EMAIL` environment variables. These are mapped to Django 6.1's `MAILERS` setting. Local development defaults to printing email messages in the console.

## Plans

- Monthly: UGX 30,000, extending access by one month.
- Six months: UGX 150,000, extending access by six months.
- The free trial is one calendar month from the account creation date. Payments made during the trial extend access from the trial end date.