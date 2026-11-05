from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("DietApp", "0005_support_question"),
    ]

    operations = [
        migrations.AddField(
            model_name="supportquestion",
            name="answer_viewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="supportquestion",
            name="question_key",
            field=models.CharField(db_index=True, max_length=64),
        ),
    ]