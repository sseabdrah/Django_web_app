# Email reminders

The app stores reminder preferences and provides an email delivery command. It does not schedule itself and does not send browser push notifications. Configure an email backend and an external scheduler on the deployment server before promising delivery.

1. Run `python manage.py migrate` and configure `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` and `DEFAULT_FROM_EMAIL` for a working mail provider. The default console backend only prints emails; it does not deliver them.
2. Set `TIME_ZONE` to the desired IANA time zone (for example `Africa/Kampala`) and restart the application and scheduler. All reminder times use this shared server time zone, not individual users' time zones.
3. Run `python manage.py send_nutrition_reminders` every minute using the host's scheduler. For example, a cron entry might invoke the project's virtualenv Python and absolute `manage.py` path every minute. Ensure the job has the same environment and working database access as the web application. Monitor failures and scheduler health.
4. Users must enable reminders and can disable them all under Settings. Water interval reminders run from start to end on the same day, inclusive. Weekly reminders run on Sunday. Messages intentionally omit health details.

A database record prevents a reminder from being sent twice for the same scheduled minute, including overlapping scheduler runs. Failed sends may be retried while that minute is current. Missed minutes are not replayed. A process crash after claiming a slot may result in a missed reminder; a crash after the mail provider accepts a message cannot guarantee exactly-once delivery. Email is not appropriate for urgent health alerts.
