from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("DietApp", "0007_users_is_active"),
    ]

    operations = [
        migrations.AddField(
            model_name="users",
            name="onboarding_complete",
            field=models.BooleanField(default=False),
        ),
    ]