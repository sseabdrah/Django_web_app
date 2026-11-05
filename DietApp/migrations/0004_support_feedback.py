from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("DietApp", "0003_set_decimal_field_precision"),
    ]

    operations = [
        migrations.CreateModel(
            name="SupportFeedback",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("question", models.CharField(max_length=500)),
                (
                    "topic",
                    models.CharField(
                        choices=[
                            ("general", "General"),
                            ("dashboard", "Dashboard"),
                            ("food_logging", "Food logging"),
                            ("meal_plan", "Meal planning"),
                            ("water", "Water tracking"),
                            ("progress", "Progress"),
                            ("goals", "Goals"),
                            ("profile", "Profile"),
                            ("settings", "Settings"),
                            ("achievements", "Achievements"),
                            ("onboarding", "Getting started"),
                            ("account", "Account"),
                        ],
                        default="general",
                        max_length=30,
                    ),
                ),
                ("helpful", models.BooleanField()),
                ("comment", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="support_feedback",
                        to="DietApp.users",
                    ),
                ),
            ],
        ),
    ]
