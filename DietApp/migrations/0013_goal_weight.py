from decimal import Decimal
from django.core.validators import MinValueValidator
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("DietApp", "0012_recipe_shopping_reminders")]
    operations = [
        migrations.AddField(
            model_name="userprofile", name="goal_weight_kg",
            field=models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0.01"))]),
        ),
    ]
