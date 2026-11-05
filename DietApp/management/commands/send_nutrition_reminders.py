"""Send reminders due in the current minute. Run once per minute from a scheduler."""
from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
from django.utils import timezone

from DietApp.models import Reminder, ReminderDelivery, UserSetting


def reminder_due(reminder, local_now):
    minute = local_now.hour * 60 + local_now.minute
    if reminder.reminder_type == "water":
        if not reminder.interval_minutes or reminder.interval_minutes <= 0 or not reminder.start_time or not reminder.end_time:
            return False
        start = reminder.start_time.hour * 60 + reminder.start_time.minute
        end = reminder.end_time.hour * 60 + reminder.end_time.minute
        return start < end and start <= minute <= end and (minute - start) % reminder.interval_minutes == 0
    if reminder.reminder_type not in {"breakfast", "lunch", "dinner", "snack", "weekly", "quote"} or not reminder.time:
        return False
    if reminder.reminder_type == "weekly" and local_now.weekday() != 6:
        return False
    return minute == reminder.time.hour * 60 + reminder.time.minute


class Command(BaseCommand):
    help = "Send enabled nutrition reminders due in the current minute."

    def handle(self, *args, **options):
        now = timezone.now()
        local_now = timezone.localtime(now)
        slot = now.replace(second=0, microsecond=0)
        disabled_users = UserSetting.objects.filter(notification_enabled=False).values_list("user_id_id", flat=True)
        reminders = Reminder.objects.filter(is_enabled=True, user_id__is_active=True).exclude(user_id__in=disabled_users).select_related("user_id")
        sent = 0
        failures = 0
        for reminder in reminders.iterator():
            if not reminder_due(reminder, local_now):
                continue
            try:
                with transaction.atomic():
                    delivery = ReminderDelivery.objects.create(reminder=reminder, scheduled_for=slot)
            except IntegrityError:
                continue
            label = reminder.get_reminder_type_display()
            try:
                # Avoid exposing health information in email; the user can open the app for details.
                delivered = send_mail("Diet Services reminder", f"It's time for your {label.lower()} reminder. Nourish Better, Live Healthier.", settings.DEFAULT_FROM_EMAIL, [reminder.user_id.email], fail_silently=False)
                if not delivered:
                    raise RuntimeError("Email backend did not accept the message")
                delivery.sent_at = timezone.now()
                delivery.save(update_fields=["sent_at"])
                sent += 1
            except Exception as exc:
                delivery.delete()  # A scheduler retry in the same minute can try again.
                failures += 1
                self.stderr.write(f"Reminder {reminder.pk} failed: {type(exc).__name__}")
        self.stdout.write(f"Sent {sent} reminder(s); {failures} failed.")
