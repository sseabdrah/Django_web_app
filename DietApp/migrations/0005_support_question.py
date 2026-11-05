from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("DietApp", "0004_support_feedback"),
    ]

    operations = [
        migrations.CreateModel(
            name="SupportQuestion",
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
                ("question_key", models.CharField(max_length=64, unique=True)),
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
                ("answer", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="support_questions",
                        to="DietApp.users",
                    ),
                ),
            ],
        ),
    ]