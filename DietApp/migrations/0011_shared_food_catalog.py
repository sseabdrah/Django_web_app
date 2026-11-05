from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [("DietApp", "0010_weight_log_per_user")]
    operations = [
        migrations.AlterField(
            model_name="food", name="user_id",
            field=models.ForeignKey(to="DietApp.users", on_delete=django.db.models.deletion.RESTRICT, null=True, blank=True),
        ),
    ]
