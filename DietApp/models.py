from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal

# Create your models here.

# 1 Users
class Users(models.Model):
    user_id = models.IntegerField(null=False, primary_key=True)
    full_name = models.CharField(max_length=30)
    email = models.EmailField(unique=True, null=False)
    password_hash = models.CharField(max_length=128, null=False)
    is_active = models.BooleanField(default=True)
    onboarding_complete = models.BooleanField(default=False)
    paid_until = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=20, unique=True)
    profile_image = models.ImageField(upload_to='profile_picture', max_length=40, blank=True)
    created_at = models.DateField(null=False)
    last_login = models.DateField(null=False)


# 2. user_profiles
class UserProfile(models.Model):
    gender_choices = [
        ('F', 'Female'),
        ('M', 'Male'),
        ('O', 'Other'),
    ]  # changed from dict to list of tuples

    activity_level_choices = [
        ('sedentary', 'Sedentary'),
        ('light', 'Lightly Active'),
        ('moderate', 'Moderately Active'),
        ('active', 'Active'),
        ('very_active', 'Very Active'),
    ]

    health_goal_choices = [
        ('lose', 'Lose Weight'),
        ('maintain', 'Maintain Weight'),
        ('gain', 'Gain Weight'),
        ('muscle', 'Build Muscle'),
    ]

    user_id = models.ForeignKey(Users, on_delete=models.RESTRICT)
    age = models.IntegerField(null=True, blank=True)
    gender = models.CharField(max_length=10, choices=gender_choices, blank=True, null=True)
    weight_kg = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    goal_weight_kg = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0.01"))])
    activity_level = models.CharField(max_length=20, choices=activity_level_choices, blank=True, null=True)
    dietary_preferences = models.JSONField(default=list, blank=True)
    health_goal = models.CharField(max_length=20, choices=health_goal_choices, blank=True, null=True)
    daily_calorie_target = models.IntegerField(null=True, blank=True)
    daily_protein_target = models.IntegerField(null=True, blank=True)
    daily_carbs_target = models.IntegerField(null=True, blank=True)
    daily_fat_target = models.IntegerField(null=True, blank=True)
    daily_water_target = models.IntegerField(null=True, blank=True)
    updated_at = models.DateField(null=False)


# 3. weight_logs
class WeightLog(models.Model):
    weight_log_id = models.IntegerField(null=False, primary_key=True)  # fixed typo
    user_id = models.ForeignKey(Users, on_delete=models.RESTRICT)
    weight_kg = models.DecimalField(max_digits=6, decimal_places=2, null=False)
    log_date = models.DateField()
    notes = models.TextField(blank=True, null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user_id", "log_date"], name="unique_weight_log_per_user_date")]


# 4. foods
class Food(models.Model):
    food_id = models.IntegerField(null=False, primary_key=True)
    name = models.CharField(max_length=255)
    brand = models.CharField(max_length=255, blank=True, null=True)
    serving_size = models.FloatField()
    serving_unit = models.CharField(max_length=50)
    calories = models.IntegerField()
    protein = models.FloatField()
    carbs = models.FloatField()
    fat = models.FloatField()
    fiber = models.FloatField(default=0)
    is_custom = models.BooleanField(default=False)
    user_id = models.ForeignKey(Users, on_delete=models.RESTRICT, null=True, blank=True)
    barcode = models.CharField(max_length=50, null=True, blank=True)


# 5. food_logs
class FoodLog(models.Model):
    MEAL_TYPE_CHOICES = [
        ('breakfast', 'Breakfast'),
        ('lunch', 'Lunch'),
        ('dinner', 'Dinner'),
        ('snack', 'Snack'),
    ]

    food_log_id = models.IntegerField(null=False, primary_key=True)
    user_id = models.ForeignKey(Users, on_delete=models.RESTRICT)
    food_id = models.ForeignKey(Food, on_delete=models.RESTRICT)
    meal_type = models.CharField(max_length=20, choices=MEAL_TYPE_CHOICES)
    quantity = models.FloatField()
    serving_unit = models.CharField(max_length=50)
    calories_consumed = models.IntegerField()
    protein_consumed = models.FloatField()
    carbs_consumed = models.FloatField()
    fat_consumed = models.FloatField()
    fiber_consumed = models.FloatField(default=0)
    log_date = models.DateField()
    log_time = models.TimeField()
    notes = models.TextField(blank=True, null=True)
    photo_path = models.CharField(max_length=255, null=True, blank=True)


# 6. water_logs
class WaterLog(models.Model):
    water_log_id = models.IntegerField(null=False, primary_key=True)
    user_id = models.ForeignKey(Users, on_delete=models.RESTRICT)
    amount_ml = models.IntegerField()
    log_date = models.DateField()
    log_time = models.TimeField()


# 7. recipes
class Recipe(models.Model):
    recipe_id = models.IntegerField(null=False, primary_key=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    image_url = models.CharField(max_length=500, blank=True, null=True)
    prep_time_minutes = models.IntegerField()
    cook_time_minutes = models.IntegerField()
    total_time_minutes = models.IntegerField()
    servings = models.IntegerField()
    calories_per_serving = models.IntegerField()
    protein_per_serving = models.FloatField()
    carbs_per_serving = models.FloatField()
    fat_per_serving = models.FloatField()
    fiber_per_serving = models.FloatField(default=0)
    instructions = models.JSONField(default=list)
    dietary_tags = models.JSONField(default=list)
    is_public = models.BooleanField(default=True)
    user_id = models.ForeignKey(Users, on_delete=models.SET_NULL, null=True, blank=True)


# 8. recipe_ingredients
class RecipeIngredient(models.Model):
    recipe_ingredients_id = models.IntegerField(null=False, primary_key=True)
    recipe_id = models.ForeignKey(Recipe, on_delete=models.RESTRICT)
    food_id = models.ForeignKey(Food, on_delete=models.SET_NULL, null=True, blank=True)
    ingredient_name = models.CharField(max_length=255, blank=True, null=True)
    quantity = models.FloatField()
    unit = models.CharField(max_length=50)


# 9. meal_plans
class MealPlan(models.Model):
    meal_type_choices = [
        ('breakfast', 'Breakfast'),
        ('lunch', 'Lunch'),
        ('dinner', 'Dinner'),
        ('snack', 'Snack'),
    ]

    meal_id = models.IntegerField(null=False, primary_key=True)
    user_id = models.ForeignKey(Users, on_delete=models.RESTRICT)
    plan_date = models.DateField()
    meal_type = models.CharField(max_length=20, choices=meal_type_choices)
    recipe_id = models.ForeignKey(Recipe, on_delete=models.SET_NULL, null=True, blank=True)
    custom_meal_name = models.CharField(max_length=255, blank=True, null=True)
    custom_meal_calories = models.IntegerField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)


# 10. achievements
class Achievement(models.Model):
    achievement_id = models.IntegerField(null=False, primary_key=True)
    name = models.CharField(max_length=255)
    description = models.TextField()
    icon_name = models.CharField(max_length=100)
    criteria_type = models.CharField(max_length=50)
    criteria_value = models.IntegerField()
    badge_image = models.CharField(max_length=255)


# 11. user_achievements
class UserAchievement(models.Model):
    user_achievement_id = models.IntegerField(null=False, primary_key=True)
    user_id = models.ForeignKey(Users, on_delete=models.RESTRICT)
    achievement_id = models.ForeignKey(Achievement, on_delete=models.RESTRICT)
    earned_date = models.DateTimeField(auto_now_add=True)
    progress = models.IntegerField(default=0)
    is_completed = models.BooleanField(default=False)


# 12. reminders
class Reminder(models.Model):
    reminder_type_choices = [
        ('breakfast', 'Breakfast'),
        ('lunch', 'Lunch'),
        ('dinner', 'Dinner'),
        ('snack', 'Snack'),
        ('water', 'Water'),
        ('weekly', 'Weekly Report'),
        ('quote', 'Daily motivation'),
    ]

    reminder_id = models.IntegerField(null=False, primary_key=True)
    user_id = models.ForeignKey(Users, on_delete=models.RESTRICT)
    reminder_type = models.CharField(max_length=20, choices=reminder_type_choices)
    is_enabled = models.BooleanField(default=True)
    time = models.TimeField(null=True, blank=True)
    interval_minutes = models.IntegerField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)


# 13. user_settings
class UserSetting(models.Model):
    unit_system_choices = [
        ('metric', 'Metric'),
        ('imperial', 'Imperial'),
    ]

    theme_choices = [
        ('light', 'Light'),
        ('dark', 'Dark'),
        ('system', 'System Default'),
    ]

    user_id = models.ForeignKey(Users, on_delete=models.RESTRICT, primary_key=True)
    unit_system = models.CharField(max_length=10, choices=unit_system_choices, default='metric')
    theme = models.CharField(max_length=10, choices=theme_choices, default='system')
    language = models.CharField(max_length=10, default='en')
    notification_enabled = models.BooleanField(default=True)


# 14. favorite_recipes
class FavoriteRecipe(models.Model):
    user_id = models.ForeignKey(Users, on_delete=models.RESTRICT)
    recipe_id = models.ForeignKey(Recipe, on_delete=models.RESTRICT)
    added_at = models.DateTimeField(auto_now_add=True)


class SupportFeedback(models.Model):
    TOPIC_CHOICES = [
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
    ]

    user = models.ForeignKey(Users, on_delete=models.CASCADE, related_name="support_feedback")
    question = models.CharField(max_length=500)
    topic = models.CharField(max_length=30, choices=TOPIC_CHOICES, default="general")
    helpful = models.BooleanField()
    comment = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class SupportQuestion(models.Model):
    TOPIC_CHOICES = SupportFeedback.TOPIC_CHOICES

    user = models.ForeignKey(
        Users,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_questions",
    )
    question = models.CharField(max_length=500)
    question_key = models.CharField(max_length=64, db_index=True)
    topic = models.CharField(max_length=30, choices=TOPIC_CHOICES, default="general")
    answer = models.TextField(blank=True)
    answer_viewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.question


class SubscriptionPayment(models.Model):
    PLAN_CHOICES = [
        ("monthly", "Monthly"),
        ("six_months", "Six months"),
    ]
    NETWORK_CHOICES = [
        ("AIRTEL", "Airtel Money"),
        ("MTN", "MTN Mobile Money"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("successful", "Successful"),
        ("failed", "Failed"),
    ]

    user = models.ForeignKey(Users, on_delete=models.PROTECT, related_name="subscription_payments")
    tx_ref = models.CharField(max_length=80, unique=True)
    provider_transaction_id = models.CharField(max_length=80, blank=True, null=True, unique=True)
    provider_reference = models.CharField(max_length=100, blank=True)
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES)
    network = models.CharField(max_length=10, choices=NETWORK_CHOICES)
    phone_number = models.CharField(max_length=20)
    amount = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="UGX")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    admin_notified_at = models.DateTimeField(blank=True, null=True)
    admin_viewed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.tx_ref} · {self.get_status_display()}"

class RecipeReview(models.Model):
    user = models.ForeignKey(Users, on_delete=models.CASCADE)
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField()
    comment = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "recipe"], name="unique_recipe_review_per_user"),
            models.CheckConstraint(condition=models.Q(rating__gte=1, rating__lte=5), name="recipe_review_rating_range"),
        ]


class ShoppingItem(models.Model):
    user = models.ForeignKey(Users, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    quantity = models.FloatField(null=True, blank=True)
    unit = models.CharField(max_length=50, blank=True)
    checked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class ReminderDelivery(models.Model):
    reminder = models.ForeignKey(Reminder, on_delete=models.CASCADE)
    scheduled_for = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["reminder", "scheduled_for"], name="unique_reminder_delivery_slot")]
