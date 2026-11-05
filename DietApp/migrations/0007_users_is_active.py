from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("DietApp", "0006_supportquestion_answer_viewed_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="users",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
    ]
