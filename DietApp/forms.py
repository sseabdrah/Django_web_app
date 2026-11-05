import re

from django import forms
from django.contrib.auth.hashers import make_password
from django.forms import ModelForm

from DietApp.models import (
    Achievement,
    FavoriteRecipe,
    Food,
    FoodLog,
    MealPlan,
    Recipe,
    RecipeIngredient,
    Reminder,
    SupportFeedback,
    SupportQuestion,
    UserAchievement,
    UserProfile,
    UserSetting,
    Users,
    WaterLog,
    WeightLog,
)


class LoginForm(forms.Form):
    role = forms.ChoiceField(
        choices=(("user", "Normal user"), ("admin", "Administrator")),
        required=False,
        initial="user",
        widget=forms.RadioSelect(attrs={"id": "login-role", "class": "role-options"}),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"id": "email", "autocomplete": "email"})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"id": "password", "autocomplete": "current-password"}
        )
    )

    def clean_role(self):
        return self.cleaned_data.get("role") or "user"


class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"autocomplete": "email"})
    )


class PasswordResetConfirmForm(forms.Form):
    password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        if password and confirm_password and password != confirm_password:
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned_data


class MobileMoneyCheckoutForm(forms.Form):
    PLAN_CHOICES = (
        ("monthly", "Monthly · UGX 30,000"),
        ("six_months", "Six months · UGX 150,000"),
    )
    NETWORK_CHOICES = (
        ("AIRTEL", "Airtel Money"),
        ("MTN", "MTN Mobile Money"),
    )

    plan = forms.ChoiceField(choices=PLAN_CHOICES)
    network = forms.ChoiceField(
        choices=NETWORK_CHOICES,
        widget=forms.RadioSelect,
        initial="MTN",
    )
    phone_number = forms.CharField(max_length=20, label="Mobile Money number")

    def clean_phone_number(self):
        phone_number = re.sub(r"[\s()-]", "", self.cleaned_data["phone_number"])
        if phone_number.startswith("+"):
            phone_number = phone_number[1:]
        if phone_number.startswith("0") and len(phone_number) == 10:
            phone_number = "256" + phone_number[1:]
        if not re.fullmatch(r"256[0-9]{9}", phone_number):
            raise forms.ValidationError("Enter a valid Uganda number, such as 0772 123456 or +256 772 123456.")
        return phone_number


class SupportQuestionForm(forms.Form):
    question = forms.CharField(
        max_length=500,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Ask about logging food, goals, progress...",
                "autocomplete": "off",
            }
        ),
    )


class SupportFeedbackForm(forms.Form):
    helpful = forms.TypedChoiceField(
        choices=(("true", "Yes, I got help"), ("false", "Not yet")),
        coerce=lambda value: value == "true",
        widget=forms.RadioSelect,
    )
    comment = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": "What could we improve?"}
        ),
    )
    question = forms.CharField(max_length=500, widget=forms.HiddenInput)
    topic = forms.ChoiceField(
        choices=SupportFeedback.TOPIC_CHOICES,
        widget=forms.HiddenInput,
    )


class RegisterForm(forms.Form):
    full_name = forms.CharField(
        max_length=30,
        widget=forms.TextInput(attrs={"id": "full-name", "autocomplete": "name"}),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"id": "email", "autocomplete": "email"})
    )
    phone = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={"id": "phone", "autocomplete": "tel"}),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"id": "password", "autocomplete": "new-password"}
        )
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"id": "confirm-password", "autocomplete": "new-password"}
        )
    )

    def clean_email(self):
        email = self.cleaned_data["email"]
        from django.conf import settings
        admin_email = getattr(settings, "DIETAPP_ADMIN_EMAIL", "")
        if admin_email and email.casefold() == admin_email.casefold():
            raise forms.ValidationError("This email address is reserved.")
        if Users.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_phone(self):
        phone = self.cleaned_data["phone"]
        if Users.objects.filter(phone=phone).exists():
            raise forms.ValidationError("An account with this phone number already exists.")
        return phone

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        if password and confirm_password and password != confirm_password:
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned_data


class UsersForm(ModelForm):
    password = forms.CharField(
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = Users
        exclude = ("password_hash",)

    def clean(self):
        cleaned_data = super().clean()
        if self.instance._state.adding and not cleaned_data.get("password"):
            self.add_error("password", "A password is required.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            user.password_hash = make_password(password)
        if commit:
            user.save()
            self.save_m2m()
        return user


class AdminUserForm(UsersForm):
    class Meta:
        model = Users
        fields = ("full_name", "email", "phone", "profile_image", "is_active", "password")

    def clean_email(self):
        email = self.cleaned_data["email"]
        from django.conf import settings
        admin_email = getattr(settings, "DIETAPP_ADMIN_EMAIL", "")
        if admin_email and email.casefold() == admin_email.casefold() and (
            not self.instance.pk or self.instance.email.casefold() != admin_email.casefold()
        ):
            raise forms.ValidationError("The configured administrator email is reserved.")
        duplicate = Users.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_phone(self):
        phone = self.cleaned_data["phone"]
        duplicate = Users.objects.filter(phone=phone).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError("An account with this phone number already exists.")
        return phone


class AdminFoodForm(ModelForm):
    class Meta:
        model = Food
        exclude = ("food_id",)


class AdminRecipeForm(ModelForm):
    class Meta:
        model = Recipe
        exclude = ("recipe_id",)


class AdminMealPlanForm(ModelForm):
    class Meta:
        model = MealPlan
        exclude = ("meal_id",)


class AdminSupportAnswerForm(ModelForm):
    class Meta:
        model = SupportQuestion
        fields = ("answer",)
        widgets = {"answer": forms.Textarea(attrs={"rows": 7})}


class AccountDetailsForm(ModelForm):
    class Meta:
        model = Users
        fields = ("full_name", "email", "phone", "profile_image")


class UserProfileForm(ModelForm):
    class Meta:
        model = UserProfile
        exclude = ("user_id", "updated_at")


class GoalsForm(ModelForm):
    class Meta:
        model = UserProfile
        fields = (
            "health_goal",
            "daily_calorie_target",
            "daily_protein_target",
            "daily_carbs_target",
            "daily_fat_target",
            "daily_water_target",
        )


class SettingsForm(ModelForm):
    class Meta:
        model = UserSetting
        exclude = ("user_id",)


class WeightLogForm(ModelForm):
    class Meta:
        model = WeightLog
        fields = "__all__"


class FoodForm(ModelForm):
    class Meta:
        model = Food
        fields = "__all__"


class FoodLogForm(ModelForm):
    class Meta:
        model = FoodLog
        fields = "__all__"


class WaterLogForm(ModelForm):
    class Meta:
        model = WaterLog
        fields = "__all__"


class RecipeForm(ModelForm):
    class Meta:
        model = Recipe
        fields = "__all__"


class RecipeIngredientForm(ModelForm):
    class Meta:
        model = RecipeIngredient
        fields = "__all__"


class MealPlanForm(ModelForm):
    class Meta:
        model = MealPlan
        fields = "__all__"


class AchievementForm(ModelForm):
    class Meta:
        model = Achievement
        fields = "__all__"


class UserAchievementForm(ModelForm):
    class Meta:
        model = UserAchievement
        fields = "__all__"


class ReminderForm(ModelForm):
    class Meta:
        model = Reminder
        fields = "__all__"


RemindersForm = ReminderForm


class UserSettingForm(SettingsForm):
    pass


class FavoriteRecipeForm(ModelForm):
    class Meta:
        model = FavoriteRecipe
        fields = "__all__"

