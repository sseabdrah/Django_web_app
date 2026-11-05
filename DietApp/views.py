import hashlib
import hmac
import json
import re
import uuid
import calendar
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login as auth_login, logout as auth_logout
from django.contrib.auth.hashers import check_password, make_password
from django.contrib import messages
from django.core import signing
from django.core.mail import send_mail
from django.core.exceptions import PermissionDenied
from django.db import models, transaction
from django.db.models.deletion import RestrictedError
from django.db.models import Max, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.urls import reverse

from DietApp.ai_support import generate_diet_ai_answer
from DietApp.forms import (
    AchievementForm,
    AccountDetailsForm,
    AdminFoodForm,
    AdminMealPlanForm,
    AdminRecipeForm,
    AdminSupportAnswerForm,
    AdminUserForm,
    FavoriteRecipeForm,
    FoodForm,
    FoodLogForm,
    GoalsForm,
    LoginForm,
    MobileMoneyCheckoutForm,
    PasswordResetConfirmForm,
    PasswordResetRequestForm,
    MealPlanForm,
    RecipeForm,
    RecipeIngredientForm,
    RegisterForm,
    ReminderForm,
    SettingsForm,
    SupportFeedbackForm,
    SupportQuestionForm,
    UserAchievementForm,
    UserProfileForm,
    UserSettingForm,
    UsersForm,
    WaterLogForm,
    WeightLogForm,
)
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
    SubscriptionPayment,
    UserAchievement,
    UserProfile,
    UserSetting,
    Users,
    WaterLog,
    WeightLog,
)
from DietApp.payments import (
    PaymentProviderError,
    initiate_uganda_mobile_money,
    payment_provider_ready,
    verify_uganda_mobile_money,
)

MODEL_FORM_REGISTRY = {
    "users": ("Account details", UsersForm),
    "user-profiles": ("Profile", UserProfileForm),
    "weight-logs": ("Weight log", WeightLogForm),
    "foods": ("Food", FoodForm),
    "food-logs": ("Food log", FoodLogForm),
    "water-logs": ("Water log", WaterLogForm),
    "recipes": ("Recipe", RecipeForm),
    "recipe-ingredients": ("Recipe ingredient", RecipeIngredientForm),
    "meal-plans": ("Meal plan", MealPlanForm),
    "achievements": ("Achievement", AchievementForm),
    "user-achievements": ("User achievement", UserAchievementForm),
    "reminders": ("Reminder", ReminderForm),
    "user-settings": ("Settings", UserSettingForm),
    "favorite-recipes": ("Favorite recipe", FavoriteRecipeForm),
}


def _get_logged_in_user(request, allow_unpaid=False):
    user_id = request.session.get("user_id")
    if not user_id:
        return None, redirect("login")

    user = Users.objects.filter(pk=user_id, is_active=True).first()
    if not user:
        request.session.pop("user_id", None)
        return None, redirect("login")
    if not allow_unpaid and payment_provider_ready() and not _subscription_is_current(user):
        return None, redirect("subscription")
    return user, None


def _add_months(value, months):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1]))


def _subscription_is_current(user):
    today = timezone.localdate()
    trial_end = _trial_end_date(user.created_at)
    return today < trial_end or bool(user.paid_until and user.paid_until >= today)


def Home(request):
    return render(request, "home.html")


def _sync_admin_account(user, password):
    admin_email = getattr(settings, "DIETAPP_ADMIN_EMAIL", "")
    if not user.is_active or user.email.casefold() != admin_email.casefold():
        return None

    auth_user_model = get_user_model()
    matching_users = list(
        auth_user_model._default_manager.filter(email__iexact=admin_email)[:2]
    )
    if len(matching_users) > 1:
        return None

    admin_user = matching_users[0] if matching_users else None
    if admin_user and not admin_user.is_staff:
        return None
    if admin_user is None:
        username_field = auth_user_model.USERNAME_FIELD
        username = user.email
        if auth_user_model._default_manager.filter(**{username_field: username}).exists():
            return None
        admin_user = auth_user_model(**{username_field: username})

    admin_user.email = user.email
    if hasattr(admin_user, "first_name"):
        name_parts = user.full_name.split(maxsplit=1)
        admin_user.first_name = name_parts[0]
        admin_user.last_name = name_parts[1] if len(name_parts) > 1 else ""
    admin_user.is_active = True
    admin_user.is_staff = True
    admin_user.is_superuser = True
    admin_user.set_password(password)
    admin_user.save()
    return admin_user


def _authenticate_admin_account(request, email, password):
    auth_user_model = get_user_model()
    matching_users = list(
        auth_user_model._default_manager.filter(
            email__iexact=email, is_active=True, is_staff=True
        )[:2]
    )
    if len(matching_users) != 1:
        return None

    admin_user = matching_users[0]
    username_field = auth_user_model.USERNAME_FIELD
    admin_user = authenticate(
        request,
        **{username_field: getattr(admin_user, username_field), "password": password},
    )
    if not admin_user or not admin_user.is_staff or not admin_user.email:
        return None

    app_user = Users.objects.filter(email__iexact=admin_user.email).first()
    if app_user and not app_user.is_active:
        return None
    if not app_user:
        last_user_id = Users.objects.aggregate(max_id=Max("user_id"))["max_id"] or 0
        full_name = " ".join(
            part for part in (admin_user.first_name, admin_user.last_name) if part
        ) or admin_user.get_username()
        app_user = Users.objects.create(
            user_id=last_user_id + 1,
            full_name=full_name[:30],
            email=admin_user.email,
            password_hash=make_password(password),
            phone=f"admin-{last_user_id + 1}",
            created_at=timezone.localdate(),
            last_login=timezone.localdate(),
        )
    return admin_user, app_user


def Login(request):
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        password = form.cleaned_data["password"]
        role = form.cleaned_data["role"]

        if role == "admin":
            app_user = Users.objects.filter(email__iexact=email).first()
            admin_user = None
            if app_user and email.casefold() == getattr(
                settings, "DIETAPP_ADMIN_EMAIL", ""
            ).casefold() and (
                check_password(password, app_user.password_hash)
                or app_user.password_hash == password
            ):
                admin_user = _sync_admin_account(app_user, password)
            if admin_user:
                app_user.last_login = timezone.localdate()
                app_user.save(update_fields=["last_login"])
                auth_login(request, admin_user, backend="django.contrib.auth.backends.ModelBackend")
                request.session["user_id"] = app_user.pk
                return redirect("admin_dashboard")

            admin_login = _authenticate_admin_account(request, email, password)
            if admin_login:
                admin_user, app_user = admin_login
                app_user.last_login = timezone.localdate()
                app_user.save(update_fields=["last_login"])
                auth_login(request, admin_user, backend="django.contrib.auth.backends.ModelBackend")
                request.session["user_id"] = app_user.pk
                return redirect("admin_dashboard")
        else:
            user = Users.objects.filter(email__iexact=email).first()
            is_configured_admin = email.casefold() == getattr(
                settings, "DIETAPP_ADMIN_EMAIL", ""
            ).casefold()
            is_django_admin = get_user_model()._default_manager.filter(
                email__iexact=email, is_active=True, is_staff=True
            ).exists()
            if user and user.is_active and not is_configured_admin and not is_django_admin and (
                check_password(password, user.password_hash) or user.password_hash == password
            ):
                updated_fields = []
                if user.password_hash == password:
                    user.password_hash = make_password(password)
                    updated_fields.append("password_hash")
                user.last_login = timezone.localdate()
                updated_fields.append("last_login")
                user.save(update_fields=updated_fields)
                auth_logout(request)
                request.session["user_id"] = user.pk
                return redirect("dashboard" if user.onboarding_complete else "onboarding")

        form.add_error(None, "Email or password is incorrect.")

    return render(request, "login.html", {"form": form})


def PasswordResetRequest(request):
    form = PasswordResetRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = Users.objects.filter(
            email__iexact=form.cleaned_data["email"]
        ).first()
        if user:
            token = signing.dumps(
                {"user_id": user.pk, "password_hash": user.password_hash},
                salt="DietApp.password-reset",
            )
            reset_url = request.build_absolute_uri(
                reverse("password_reset_confirm", kwargs={"token": token})
            )
            send_mail(
                "Reset your Diet Services password",
                f"Use this link within one hour to reset your password:\n\n{reset_url}\n\nIf you did not request this, you can ignore this email.",
                None,
                [user.email],
                fail_silently=False,
            )
        return render(request, "password_reset_request.html", {"form": form, "sent": True})
    return render(request, "password_reset_request.html", {"form": form})


def PasswordResetConfirm(request, token):
    try:
        payload = signing.loads(
            token, salt="DietApp.password-reset", max_age=3600
        )
    except signing.BadSignature:
        payload = None
    user = None
    if payload:
        user = Users.objects.filter(
            pk=payload.get("user_id"),
            password_hash=payload.get("password_hash"),
        ).first()
    if not user:
        return render(request, "password_reset_confirm.html", {"invalid_link": True})

    form = PasswordResetConfirmForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user.password_hash = make_password(form.cleaned_data["password"])
        user.save(update_fields=["password_hash"])
        messages.success(request, "Your password has been reset. You can now log in.")
        return redirect("login")
    return render(request, "password_reset_confirm.html", {"form": form})


@require_POST
def Logout(request):
    request.session.flush()
    return redirect("login")


def _activity_streak(user, today):
    activity_dates = set(
        FoodLog.objects.filter(user_id=user).values_list("log_date", flat=True)
    )
    activity_dates.update(
        WaterLog.objects.filter(user_id=user).values_list("log_date", flat=True)
    )
    activity_dates.update(
        WeightLog.objects.filter(user_id=user).values_list("log_date", flat=True)
    )

    streak_end = today if today in activity_dates else today - timedelta(days=1)
    current = 0
    while streak_end - timedelta(days=current) in activity_dates:
        current += 1

    best = 0
    run = 0
    previous = None
    for active_day in sorted(activity_dates):
        run = run + 1 if previous and active_day == previous + timedelta(days=1) else 1
        best = max(best, run)
        previous = active_day

    calendar = []
    for offset in range(27, -1, -1):
        active_day = today - timedelta(days=offset)
        calendar.append({"date": active_day, "active": active_day in activity_dates})
    return {"current": current, "best": best, "calendar": calendar}


def Dashboard(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("admin_dashboard")
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response

    cards = [
        {"title": "Account Details", "description": "Review your account information", "url": reverse("account_details")},
        {"title": "Profile", "description": "Manage your personal measurements and preferences", "url": reverse("profile")},
        {"title": "Food Log", "description": "Review meals, food, and water records", "url": reverse("food_log")},
        {"title": "Goals", "description": "Set your nutrition and hydration targets", "url": reverse("goals")},
        {"title": "Achievements", "description": "See the milestones you have earned", "url": reverse("achievements")},
        {"title": "Settings", "description": "Manage units and notifications", "url": reverse("settings")},
    ]
    today = timezone.localdate()
    profile = _profile_for_user(user)
    intake = FoodLog.objects.filter(user_id=user, log_date=today).aggregate(
        calories=Sum("calories_consumed"),
        protein=Sum("protein_consumed"),
        carbs=Sum("carbs_consumed"),
        fat=Sum("fat_consumed"),
    )
    water_ml = WaterLog.objects.filter(user_id=user, log_date=today).aggregate(
        amount=Sum("amount_ml")
    )["amount"] or 0
    today_meals = (
        FoodLog.objects.filter(user_id=user, log_date=today)
        .select_related("food_id")
        .order_by("log_time")
    )
    targets = {
        "calories": profile.daily_calorie_target if profile else None,
        "protein": profile.daily_protein_target if profile else None,
        "carbs": profile.daily_carbs_target if profile else None,
        "fat": profile.daily_fat_target if profile else None,
        "water": profile.daily_water_target if profile else None,
    }
    daily_summary = {
        "date": today,
        "calories": intake["calories"] or 0,
        "protein": intake["protein"] or 0,
        "carbs": intake["carbs"] or 0,
        "fat": intake["fat"] or 0,
        "water_ml": water_ml,
        "targets": targets,
    }
    has_profile = profile is not None
    has_settings = UserSetting.objects.filter(user_id=user).exists()
    streak = _activity_streak(user, today)
    answered_support_questions = list(
        SupportQuestion.objects.filter(
            user=user,
            answer__gt="",
            answer_viewed_at__isnull=True,
        ).order_by("updated_at")
    )
    if answered_support_questions:
        SupportQuestion.objects.filter(
            pk__in=[item.pk for item in answered_support_questions]
        ).update(answer_viewed_at=timezone.now())
    for key in ("calories", "protein", "carbs", "fat"):
        target = targets[key]
        daily_summary[f"{key}_progress"] = min(
            100, round(daily_summary[key] / target * 100)
        ) if target else 0
    daily_summary["water_progress"] = min(
        100, round(water_ml / targets["water"] * 100)
    ) if targets["water"] else 0
    return render(
        request,
        "dashboard.html",
        {
            "user": user,
            "modules": cards,
            "daily_summary": daily_summary,
            "today_meals": today_meals,
            "streak": streak,
            "profile_setup_required": not has_profile,
            "answered_support_questions": answered_support_questions,
        },
    )


def GettingStarted(request):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response
    profile = _profile_for_user(user)
    return render(
        request,
        "getting_started.html",
        {
            "user": user,
            "profile_complete": profile is not None,
            "goals_complete": bool(profile and profile.health_goal),
            "settings_complete": UserSetting.objects.filter(user_id=user).exists(),
        },
    )


def Onboarding(request):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response
    if user.onboarding_complete:
        return redirect("dashboard")

    if request.method == "POST":
        user.onboarding_complete = True
        user.save(update_fields=["onboarding_complete"])
        destinations = {
            "dashboard": "dashboard",
            "getting_started": "getting_started",
        }
        return redirect(destinations.get(request.POST.get("destination"), "dashboard"))

    return render(request, "onboarding.html", {"user": user})


def _trial_end_date(created_at):
    next_month = (created_at.replace(day=28) + timedelta(days=4)).replace(day=1)
    following_month = (next_month.replace(day=28) + timedelta(days=4)).replace(day=1)
    last_day = (following_month - timedelta(days=1)).day
    return next_month.replace(day=min(created_at.day, last_day))


def Subscription(request):
    user, redirect_response = _get_logged_in_user(request, allow_unpaid=True)
    if redirect_response:
        return redirect_response
    today = timezone.localdate()
    trial_ends_on = _trial_end_date(user.created_at)
    trial_active = today < trial_ends_on
    payment_form = MobileMoneyCheckoutForm(
        request.POST or None,
        initial={"phone_number": user.phone},
    )
    if request.method == "POST":
        if not payment_provider_ready():
            messages.error(
                request,
                "Mobile Money is not connected yet, so no payment request was sent.",
            )
        elif payment_form.is_valid():
            plan = payment_form.cleaned_data["plan"]
            amount = 30000 if plan == "monthly" else 150000
            payment = SubscriptionPayment.objects.create(
                user=user,
                tx_ref=f"diet-{uuid.uuid4().hex}",
                plan=plan,
                network=payment_form.cleaned_data["network"],
                phone_number=payment_form.cleaned_data["phone_number"],
                amount=amount,
            )
            callback_url = request.build_absolute_uri(reverse("subscription_return"))
            try:
                provider_url = initiate_uganda_mobile_money(payment, callback_url)
            except PaymentProviderError as error:
                payment.status = "failed"
                payment.save(update_fields=["status"])
                messages.error(request, str(error))
            else:
                return redirect(provider_url)
    return render(
        request,
        "subscription.html",
        {
            "user": user,
            "today": today,
            "trial_ends_on": trial_ends_on,
            "trial_active": trial_active,
            "trial_days_remaining": max(0, (trial_ends_on - today).days),
            "trial_days_elapsed": max(0, (today - trial_ends_on).days),
            "paid_until": user.paid_until,
            "payment_form": payment_form,
            "payment_ready": payment_provider_ready(),
            "recent_payments": SubscriptionPayment.objects.filter(user=user)[:5],
        },
    )


def _notify_admin_of_payment(payment_id):
    payment = SubscriptionPayment.objects.select_related("user").get(pk=payment_id)
    recipient = getattr(settings, "DIETAPP_ADMIN_EMAIL", "")
    if not recipient or payment.admin_notified_at:
        return
    sent = send_mail(
        subject="Diet Services: subscription payment received",
        message=(
            f"A verified payment was received from {payment.user.full_name} "
            f"({payment.user.email}).\n"
            f"Amount: {payment.currency} {payment.amount:,}\n"
            f"Plan: {payment.get_plan_display()}\n"
            f"Network: {payment.get_network_display()}\n"
            f"Reference: {payment.tx_ref}"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recipient],
        fail_silently=True,
    )
    if sent:
        SubscriptionPayment.objects.filter(
            pk=payment_id, admin_notified_at__isnull=True
        ).update(admin_notified_at=timezone.now())


def _verify_and_apply_payment(tx_ref, provider_transaction_id):
    payment = SubscriptionPayment.objects.filter(tx_ref=tx_ref).first()
    if not payment or not provider_transaction_id:
        return False
    try:
        verified = verify_uganda_mobile_money(provider_transaction_id)
    except PaymentProviderError:
        return False
    if (
        str(verified.get("id")) != str(provider_transaction_id)
        or verified.get("tx_ref") != payment.tx_ref
        or verified.get("status") != "successful"
        or verified.get("currency", "").upper() != payment.currency
        or float(verified.get("amount", 0)) < payment.amount
    ):
        return False

    with transaction.atomic():
        payment = SubscriptionPayment.objects.select_for_update().select_related("user").get(pk=payment.pk)
        if payment.status == "successful":
            return True
        payment.status = "successful"
        payment.provider_transaction_id = str(provider_transaction_id)
        payment.provider_reference = str(verified.get("flw_ref", ""))[:100]
        payment.paid_at = timezone.now()
        payment.save(
            update_fields=(
                "status",
                "provider_transaction_id",
                "provider_reference",
                "paid_at",
            )
        )
        user = Users.objects.select_for_update().get(pk=payment.user_id)
        today = timezone.localdate()
        base_date = max(
            today,
            _trial_end_date(user.created_at),
            user.paid_until or today,
        )
        months = 1 if payment.plan == "monthly" else 6
        user.paid_until = _add_months(base_date, months)
        user.save(update_fields=["paid_until"])
        transaction.on_commit(lambda: _notify_admin_of_payment(payment.pk))
    return True


@require_GET
def SubscriptionReturn(request):
    user, redirect_response = _get_logged_in_user(request, allow_unpaid=True)
    if redirect_response:
        return redirect_response
    tx_ref = request.GET.get("tx_ref", "")
    payment = SubscriptionPayment.objects.filter(tx_ref=tx_ref, user=user).first()
    transaction_id = request.GET.get("transaction_id", "")
    if payment and transaction_id and _verify_and_apply_payment(tx_ref, transaction_id):
        messages.success(request, "Payment confirmed. Your subscription access has been extended.")
    elif payment:
        messages.info(
            request,
            "Payment is awaiting Mobile Money approval. Check your phone for the "
            "Airtel Money or MTN prompt and enter your PIN on your phone to approve it. "
            "Diet Services will never ask for your PIN.",
        )
    else:
        messages.error(request, "We could not match that payment to your account.")
    return redirect("subscription")


@csrf_exempt
@require_POST
def FlutterwaveWebhook(request):
    secret_hash = getattr(settings, "FLW_SECRET_HASH", "")
    signature = request.headers.get("verif-hash", "")
    if not secret_hash or not hmac.compare_digest(signature, secret_hash):
        return HttpResponse(status=401)
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponse(status=400)
    if payload.get("event") != "charge.completed":
        return HttpResponse(status=200)
    data = payload.get("data") or {}
    tx_ref = data.get("tx_ref", "")
    payment = SubscriptionPayment.objects.filter(tx_ref=tx_ref).first()
    if not payment:
        return HttpResponse(status=200)
    if data.get("status") == "successful":
        if not _verify_and_apply_payment(tx_ref, data.get("id")):
            return HttpResponse(status=503)
    elif data.get("status") == "failed":
        SubscriptionPayment.objects.filter(pk=payment.pk, status="pending").update(status="failed")
    return HttpResponse(status=200)


def _support_answer(question):
    text = question.casefold()
    topics = [
        {
            "topic": "diet_benefits",
            "matches": (
                "benefits of diet",
                "benefits of a diet",
                "benefits of healthy eating",
                "benefits of a healthy diet",
                "benefits of balanced diet",
                "why is a healthy diet",
            ),
            "answer": (
                "A balanced, varied diet provides energy and essential nutrients. It can "
                "support normal body functions, digestive health, strong bones, and a "
                "healthy weight, and may lower the risk of some long-term conditions "
                "when combined with other healthy habits. Needs vary from person to "
                "person, so this is general information rather than personal medical advice."
            ),
        },
        {
            "topic": "logout",
            "matches": ("log out", "logout", "sign out", "signout"),
            "answer": "To securely log out of Diet Services, use the button below. You’ll be taken to the sign-in page afterward.",
            "action": "logout",
        },
        {
            "topic": "signin",
            "matches": ("sign in", "signin", "log in", "login", "how do i sign", "how to sign"),
            "answer": "Open the sign-in page and enter your email and password. If you have not created an account yet, you can register there too.",
            "url_name": "login",
            "link_label": "Go to sign in",
            "secondary_url_name": "register",
            "secondary_link_label": "Create an account",
        },
        {
            "topic": "meal_plan",
            "matches": ("meal plan", "plan a meal", "planned meals"),
            "answer": "Open Meal Plan to add upcoming meals or review your existing plan. You can also explore recipes before planning.",
            "url_name": "meal_plan",
            "link_label": "Open Meal Plan",
        },
        {
            "topic": "water",
            "matches": ("water", "hydration", "drink"),
            "answer": "You can record water from the Food Log area. Choose the water log form, enter the amount, and save it to update your daily total.",
            "url_name": "model_form",
            "url_args": ("water-logs",),
            "link_label": "Log water",
        },
        {
            "topic": "goals",
            "matches": ("goal", "target", "calorie target", "daily target"),
            "answer": "Your daily nutrition and hydration targets are managed in Goals. Update them there to use them on your dashboard and progress page.",
            "url_name": "goals",
            "link_label": "Open Goals",
        },
        {
            "topic": "progress",
            "matches": ("progress", "weight", "trend", "chart"),
            "answer": "Progress shows your recent intake and weight trends. To add a weight entry, use the weight log form.",
            "url_name": "progress",
            "link_label": "View Progress",
            "secondary_url_name": "model_form",
            "secondary_url_args": ("weight-logs",),
            "secondary_link_label": "Log weight",
        },
        {
            "topic": "achievements",
            "matches": ("achievement", "badge", "streak"),
            "answer": "Your achievements page shows earned badges, activity history, and your current and best streaks.",
            "url_name": "achievements",
            "link_label": "View Achievements",
        },
        {
            "topic": "settings",
            "matches": ("setting", "units", "unit system", "notification", "theme"),
            "answer": "Settings is where you can review units, appearance, language, and notification preferences.",
            "url_name": "settings",
            "link_label": "Open Settings",
        },
        {
            "topic": "profile",
            "matches": ("profile", "measurement", "height", "personal details"),
            "answer": "Your Profile contains personal details, measurements, health goals, and daily targets. Choose Edit profile to update measurements.",
            "url_name": "profile",
            "link_label": "Open Profile",
        },
        {
            "topic": "onboarding",
            "matches": ("getting started", "setup", "set up", "new here"),
            "answer": "Getting Started walks through your profile, goals, and preferences so your tracker can be personalized.",
            "url_name": "getting_started",
            "link_label": "Continue setup",
        },
        {
            "topic": "food_logging",
            "matches": ("food", "meal", "recipe", "breakfast", "lunch", "dinner", "snack", "calorie"),
            "answer": "Search for a food or recipe in Explore, then choose Log to add it to your food log. You can also add your own foods and recipes.",
            "url_name": "food_search",
            "link_label": "Explore food and recipes",
            "secondary_url_name": "food_log",
            "secondary_link_label": "View Food Log",
        },
        {
            "topic": "dashboard",
            "matches": ("dashboard", "home", "today"),
            "answer": "Your dashboard summarizes today's calories, water, meals, goals, and recent activity.",
            "url_name": "dashboard",
            "link_label": "Open Dashboard",
        },
        {
            "topic": "account",
            "matches": ("account", "email", "password", "login", "log in"),
            "answer": "Account Details contains your name, email, and phone number. For a password change, use the password reset link on the sign-in page.",
            "url_name": "account_details",
            "link_label": "Open Account Details",
            "secondary_url_name": "password_reset_request",
            "secondary_link_label": "Reset password",
        },
    ]

    for item in topics:
        if any(match in text for match in item["matches"]):
            answer = {
                "topic": item["topic"],
                "answer": item["answer"],
                "link_url": reverse(item["url_name"], args=item.get("url_args", ()))
                if item.get("url_name")
                else None,
                "link_label": item.get("link_label"),
                "action": item.get("action"),
                "secondary_link_url": None,
                "secondary_link_label": None,
            }
            if item.get("secondary_url_name"):
                answer["secondary_link_url"] = reverse(
                    item["secondary_url_name"],
                    args=item.get("secondary_url_args", ()),
                )
                answer["secondary_link_label"] = item["secondary_link_label"]
            return answer

    return {
        "topic": "general",
        "answer": "I can help with food logging, meal plans, water, goals, progress, your profile, settings, achievements, and account navigation. Try asking about one of those. For personal medical or nutrition advice, please consult a qualified health professional.",
        "link_url": reverse("dashboard"),
        "link_label": "Open Dashboard",
        "secondary_link_url": reverse("food_search"),
        "secondary_link_label": "Explore food and recipes",
    }


def DietAI(request):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response

    question_form = SupportQuestionForm()
    feedback_form = None
    support_result = None
    if request.method == "POST":
        if request.POST.get("action") == "feedback":
            feedback_form = SupportFeedbackForm(request.POST)
            if feedback_form.is_valid():
                SupportFeedback.objects.create(
                    user=user,
                    question=feedback_form.cleaned_data["question"],
                    topic=feedback_form.cleaned_data["topic"],
                    helpful=feedback_form.cleaned_data["helpful"],
                    comment=feedback_form.cleaned_data["comment"],
                )
                messages.success(request, "Thanks for letting us know.")
                return redirect("diet_ai")
        else:
            question_form = SupportQuestionForm(request.POST)
            if question_form.is_valid():
                question = question_form.cleaned_data["question"].strip()
                support_result = _support_answer(question)
                if support_result["topic"] == "general":
                    normalized_question = " ".join(
                        re.sub(r"[^\w\s]", "", question.casefold()).split()
                    )
                    question_key = hashlib.sha256(
                        normalized_question.encode("utf-8")
                    ).hexdigest()
                    saved_question = SupportQuestion.objects.filter(
                        user=user,
                        question_key=question_key,
                    ).order_by("-created_at").first()
                    if not saved_question:
                        existing_answer = SupportQuestion.objects.filter(
                            question_key=question_key,
                            answer__gt="",
                        ).order_by("-updated_at").first()
                        saved_question = SupportQuestion.objects.create(
                            user=user,
                            question=question,
                            question_key=question_key,
                            topic="general",
                            answer=existing_answer.answer if existing_answer else "",
                        )
                    support_result = {
                        "topic": "general",
                        "question": question,
                        "answer": saved_question.answer
                        or "I couldn't find a verified answer yet, so I've submitted your question to our support team. An administrator will review it and add an answer. Ask this question again later to see their response.",
                        "answer_source": "Administrator support"
                        if saved_question.answer
                        else "Submitted to support",
                        "link_url": None,
                        "link_label": None,
                        "secondary_link_url": None,
                        "secondary_link_label": None,
                        "action": None,
                    }
                else:
                    ai_answer = generate_diet_ai_answer(
                        question,
                        support_result["topic"],
                        support_result["answer"],
                    )
                    if ai_answer:
                        support_result["answer"] = ai_answer
                        support_result["answer_source"] = "Diet AI"
                    else:
                        support_result["answer_source"] = "Diet AI quick help"
                    support_result["question"] = question
                feedback_form = SupportFeedbackForm(
                    initial={"question": question, "topic": support_result["topic"]}
                )

    return render(
        request,
        "support.html",
        {
            "user": user,
            "diet_ai_configured": bool(getattr(settings, "DIET_AI_API_KEY", "")),
            "question_form": question_form,
            "feedback_form": feedback_form,
            "support_result": support_result,
        },
    )


def Support(request):
    user_id = request.session.get("user_id")
    user = Users.objects.filter(pk=user_id).first() if user_id else None
    return render(request, "help_support.html", {"user": user})


def Progress(request):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response

    today = timezone.localdate()
    period_options = {"week": 7, "month": 30, "quarter": 90, "year": 365}
    selected_period = request.GET.get("period", "week")
    if selected_period not in period_options:
        selected_period = "week"
    period_days = period_options.get(selected_period, 7)
    start_date = today - timedelta(days=period_days - 1)
    profile = _profile_for_user(user)
    calorie_target = profile.daily_calorie_target if profile and profile.daily_calorie_target else 3000
    water_target = profile.daily_water_target if profile and profile.daily_water_target else 3000
    calories_by_day = {
        item["log_date"]: item["total"] or 0
        for item in FoodLog.objects.filter(
            user_id=user, log_date__range=(start_date, today)
        ).values("log_date").annotate(total=Sum("calories_consumed"))
    }
    water_by_day = {
        item["log_date"]: item["total"] or 0
        for item in WaterLog.objects.filter(
            user_id=user, log_date__range=(start_date, today)
        ).values("log_date").annotate(total=Sum("amount_ml"))
    }
    daily_history = []
    bucket_size = 7 if selected_period == "year" else 1
    for offset in range(0, period_days, bucket_size):
        day = start_date + timedelta(days=offset)
        bucket_end = min(today, day + timedelta(days=bucket_size - 1))
        bucket_days = (bucket_end - day).days + 1
        calories = sum(value for logged_day, value in calories_by_day.items() if day <= logged_day <= bucket_end)
        water_ml = sum(value for logged_day, value in water_by_day.items() if day <= logged_day <= bucket_end)
        daily_history.append({
            "date": day,
            "calories": calories,
            "water_ml": water_ml,
            "calories_percent": min(100, round(calories / (calorie_target * bucket_days) * 100)),
            "water_percent": min(100, round(water_ml / (water_target * bucket_days) * 100)),
        })

    weight_history = list(
        WeightLog.objects.filter(user_id=user, log_date__range=(start_date, today)).order_by("log_date")
    )
    weights = [float(entry.weight_kg) for entry in weight_history]
    lowest_weight = min(weights, default=0)
    weight_span = max(weights, default=0) - lowest_weight
    weight_chart = []
    for index, entry in enumerate(weight_history):
        weight_chart.append({
            "date": entry.log_date,
            "weight_kg": entry.weight_kg,
            "percent": round((float(entry.weight_kg) - lowest_weight) / weight_span * 75 + 20) if weight_span else 50,
            "x": round(index * 700 / max(len(weight_history) - 1, 1)),
            "y": 155 - round((float(entry.weight_kg) - lowest_weight) / weight_span * 125) if weight_span else 92,
        })
    weight_chart_points = " ".join(f"{point['x']},{point['y']}" for point in weight_chart)
    macro_totals = FoodLog.objects.filter(
        user_id=user, log_date__range=(start_date, today)
    ).aggregate(
        protein=Sum("protein_consumed"),
        carbs=Sum("carbs_consumed"),
        fat=Sum("fat_consumed"),
    )
    macro_energy = (macro_totals["protein"] or 0) * 4 + (macro_totals["carbs"] or 0) * 4 + (macro_totals["fat"] or 0) * 9
    macro_targets = {
        "Protein": (macro_totals["protein"] or 0, profile.daily_protein_target if profile else None, 4),
        "Carbohydrates": (macro_totals["carbs"] or 0, profile.daily_carbs_target if profile else None, 4),
        "Fat": (macro_totals["fat"] or 0, profile.daily_fat_target if profile else None, 9),
    }
    macros = [
        {
            "name": name,
            "average": round(total / period_days, 1),
            "target": target,
            "percent": min(100, round(total / (target * period_days) * 100)) if target else 0,
            "share": round(total * energy_factor / macro_energy * 100) if macro_energy else 0,
        }
        for name, (total, target, energy_factor) in macro_targets.items()
    ]
    weight_records = _detail_records(
        WeightLog.objects.filter(user_id=user, log_date__range=(start_date, today)).order_by("-log_date"),
        ("log_date", "weight_kg", "notes"),
    )
    period_labels = {"week": "Week", "month": "Month", "quarter": "3 Months", "year": "Year"}
    return render(
        request,
        "progress.html",
        {
            "user": user,
            "daily_history": daily_history,
            "weight_records": weight_records,
            "weight_chart": weight_chart,
            "weight_chart_points": weight_chart_points,
            "current_weight": weight_history[-1] if weight_history else None,
            "starting_weight": weight_history[0] if weight_history else None,
            "macros": macros,
            "badges": UserAchievement.objects.filter(user_id=user, is_completed=True).select_related("achievement_id").order_by("-earned_date")[:6],
            "calorie_target": calorie_target,
            "water_target": water_target,
            "selected_period": selected_period,
            "period_label": period_labels.get(selected_period, "Week"),
            "period_options": period_labels.items(),
            "period_start": start_date,
            "period_end": today,
        },
    )


def _profile_for_user(user):
    return UserProfile.objects.filter(user_id=user).order_by("-updated_at", "-pk").first()


def _detail_records(queryset, field_names, edit_slug=None, delete_route=None):
    records = []
    for instance in queryset:
        details = []
        for field_name in field_names:
            field = instance._meta.get_field(field_name)
            display_method = getattr(instance, f"get_{field_name}_display", None)
            value = display_method() if display_method else getattr(instance, field_name)
            if field.is_relation and value is not None:
                value = getattr(value, "name", None) or getattr(value, "full_name", None) or str(value)
            if value is None or value == "":
                value = "Not provided"
            details.append({"label": field.verbose_name.title(), "value": value})
        record = {"details": details}
        if edit_slug:
            record["edit_url"] = reverse("model_record_edit", args=[edit_slug, instance.pk])
        if delete_route:
            record["delete_url"] = reverse(delete_route, args=[instance.pk])
        records.append(record)
    return records


def _module_page(request, title, intro, groups, actions=None):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response
    return render(
        request,
        "module_detail.html",
        {
            "user": user,
            "title": title,
            "intro": intro,
            "groups": groups,
            "actions": actions or [],
        },
    )


def AccountDetails(request):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response
    records = _detail_records(
        Users.objects.filter(pk=user.pk),
        ("user_id", "full_name", "email", "phone", "profile_image", "created_at", "last_login"),
    )
    return _module_page(
        request,
        "Account Details",
        "Your account information.",
        [{"title": "Account", "records": records}],
        [{"label": "Edit Account Details", "url": reverse("account_edit")}],
    )


def AccountDetailsFormPage(request):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response
    form = AccountDetailsForm(request.POST or None, request.FILES or None, instance=user)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, "Account details saved successfully.")
            return redirect("account_details")
        messages.error(request, "Please correct the errors below.")
    return render(
        request,
        "module_form.html",
        {"form": form, "title": "Edit Account Details", "cancel_url": reverse("account_details")},
    )


def Profile(request):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response
    profile = _profile_for_user(user)
    return render(
        request,
        "profile.html",
        {
            "user": user,
            "profile": profile,
            "settings": UserSetting.objects.filter(user_id=user).first(),
            "latest_weight": WeightLog.objects.filter(user_id=user).order_by("-log_date").first(),
            "weight_history": WeightLog.objects.filter(user_id=user).order_by("-log_date")[:5],
            "profile_edit_url": reverse("profile_edit") if profile else reverse("profile_add"),
            "weight_log_url": reverse("model_form", args=["weight-logs"]),
            "account_edit_url": reverse("account_edit"),
            "goals_url": reverse("goals"),
            "settings_url": reverse("settings"),
        },
    )


def DietInformation(request):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response
    groups = [
        {"title": "Your foods", "records": _detail_records(Food.objects.filter(user_id=user).order_by("name"), ("name", "brand", "serving_size", "serving_unit", "calories", "protein", "carbs", "fat", "fiber", "barcode"), "foods", "food_delete")},
        {"title": "Food diary", "records": _detail_records(FoodLog.objects.filter(user_id=user).order_by("-log_date", "-log_time"), ("food_id", "meal_type", "quantity", "serving_unit", "calories_consumed", "protein_consumed", "carbs_consumed", "fat_consumed", "fiber_consumed", "log_date", "log_time", "notes"), "food-logs")},
        {"title": "Water intake", "records": _detail_records(WaterLog.objects.filter(user_id=user).order_by("-log_date", "-log_time"), ("amount_ml", "log_date", "log_time"), "water-logs")},
        {"title": "Meal plans", "records": _detail_records(MealPlan.objects.filter(user_id=user).order_by("plan_date"), ("plan_date", "meal_type", "recipe_id", "custom_meal_name", "custom_meal_calories"), "meal-plans")},
        {"title": "Your recipes", "records": _detail_records(Recipe.objects.filter(user_id=user).order_by("name"), ("name", "description", "servings", "calories_per_serving", "protein_per_serving", "carbs_per_serving", "fat_per_serving", "fiber_per_serving", "total_time_minutes", "dietary_tags", "instructions"), "recipes")},
        {"title": "Public recipes", "records": _detail_records(Recipe.objects.filter(is_public=True).order_by("name"), ("name", "description", "servings", "calories_per_serving", "protein_per_serving", "carbs_per_serving", "fat_per_serving", "fiber_per_serving", "total_time_minutes", "dietary_tags", "instructions"))},
        {"title": "Recipe ingredients", "records": _detail_records(RecipeIngredient.objects.filter(recipe_id__user_id=user).select_related("recipe_id", "food_id"), ("recipe_id", "food_id", "ingredient_name", "quantity", "unit"), "recipe-ingredients")},
        {"title": "Favorite recipes", "records": _detail_records(FavoriteRecipe.objects.filter(user_id=user).select_related("recipe_id"), ("recipe_id", "added_at"), "favorite-recipes")},
    ]
    actions = [
        {"label": "Add Food", "url": reverse("model_form", args=["foods"])},
        {"label": "Add Food Log", "url": reverse("model_form", args=["food-logs"])},
        {"label": "Add Water Log", "url": reverse("model_form", args=["water-logs"])},
        {"label": "Add Meal Plan", "url": reverse("model_form", args=["meal-plans"])},
        {"label": "Add Recipe", "url": reverse("model_form", args=["recipes"])},
        {"label": "Add Recipe Ingredient", "url": reverse("model_form", args=["recipe-ingredients"])},
        {"label": "Add Favorite Recipe", "url": reverse("model_form", args=["favorite-recipes"])},
    ]
    return _module_page(request, "Food Log", "Your food, hydration, and meal planning records.", groups, actions)


def FoodSearch(request):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response

    query = request.GET.get("q", "").strip()
    foods = Food.objects.filter(user_id=user).order_by("name")
    recipes = Recipe.objects.filter(Q(user_id=user) | Q(is_public=True)).order_by("name")
    if query:
        foods = foods.filter(
            Q(name__icontains=query)
            | Q(brand__icontains=query)
            | Q(barcode__icontains=query)
        )
        recipes = recipes.filter(Q(name__icontains=query) | Q(description__icontains=query))
    return render(
        request,
        "food_search.html",
        {"user": user, "query": query, "foods": foods, "recipes": recipes},
    )


def FoodDetail(request, record_id):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response
    food = get_object_or_404(Food, pk=record_id, user_id=user)
    return render(request, "food_detail.html", {"user": user, "food": food})


def RecipeDetail(request, record_id):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response
    recipe = get_object_or_404(
        Recipe.objects.filter(Q(user_id=user) | Q(is_public=True)), pk=record_id
    )
    ingredients = RecipeIngredient.objects.filter(recipe_id=recipe).select_related("food_id")
    is_favorite = FavoriteRecipe.objects.filter(user_id=user, recipe_id=recipe).exists()
    return render(
        request,
        "recipe_detail.html",
        {"user": user, "recipe": recipe, "ingredients": ingredients, "is_favorite": is_favorite},
    )


def MealPlanPage(request):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response
    today = timezone.localdate()
    plans = MealPlan.objects.filter(user_id=user, plan_date__gte=today).order_by(
        "plan_date", "meal_type"
    )
    return render(
        request,
        "meal_plan.html",
        {
            "user": user,
            "plans": _detail_records(
                plans,
                ("plan_date", "meal_type", "recipe_id", "custom_meal_name", "custom_meal_calories", "notes"),
                "meal-plans",
            ),
        },
    )


def Goals(request):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response
    profile = _profile_for_user(user)
    fields = ("health_goal", "daily_calorie_target", "daily_protein_target", "daily_carbs_target", "daily_fat_target", "daily_water_target")
    records = _detail_records(
        UserProfile.objects.filter(pk=profile.pk) if profile else UserProfile.objects.none(), fields
    )
    return _module_page(
        request,
        "Goals",
        "Your health goal and daily nutrition targets.",
        [{"title": "Targets", "records": records}],
        [{"label": "Edit Goal" if profile else "Add Goal", "url": reverse("goals_edit")}],
    )


def Achievements(request):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response
    user_achievements = UserAchievement.objects.filter(user_id=user).select_related(
        "achievement_id"
    ).order_by("-earned_date")
    status_by_id = {}
    for item in user_achievements:
        status_by_id.setdefault(item.achievement_id_id, item)

    badges = []
    for achievement in Achievement.objects.all().order_by("name"):
        status = status_by_id.get(achievement.pk)
        completed = bool(status and status.is_completed)
        target = achievement.criteria_value
        progress = status.progress if status else 0
        percentage = min(100, round(progress / target * 100)) if target > 0 else 0
        icon_name = achievement.icon_name.casefold()
        if any(term in icon_name for term in ("streak", "fire", "flame")):
            icon = "🔥"
        elif any(term in icon_name for term in ("water", "drop", "hydration")):
            icon = "💧"
        elif any(term in icon_name for term in ("calorie", "energy")):
            icon = "⚡"
        elif any(term in icon_name for term in ("macro", "protein")):
            icon = "🥗"
        elif any(term in icon_name for term in ("weight", "scale")):
            icon = "⚖️"
        elif any(term in icon_name for term in ("meal", "food")):
            icon = "🍽️"
        else:
            icon = "🏅"
        badges.append({
            "name": achievement.name,
            "description": achievement.description,
            "icon": icon,
            "completed": completed,
            "progress": progress,
            "target": target,
            "percentage": 100 if completed else percentage,
            "earned_date": status.earned_date if completed else None,
        })
    badges.sort(key=lambda badge: (not badge["completed"], badge["name"].casefold()))
    streak = _activity_streak(user, timezone.localdate())
    return render(
        request,
        "achievements.html",
        {"user": user, "badges": badges, "streak": streak},
    )


def Settings(request):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response
    setting = UserSetting.objects.filter(user_id=user).first()
    records = _detail_records(
        UserSetting.objects.filter(user_id=user), ("unit_system", "theme", "language", "notification_enabled")
    )
    reminders = _detail_records(
        Reminder.objects.filter(user_id=user).order_by("reminder_type"),
        ("reminder_type", "is_enabled", "time", "interval_minutes", "start_time", "end_time"),
        "reminders",
    )
    return _module_page(
        request,
        "Settings",
        "Your display and notification preferences.",
        [{"title": "Preferences", "records": records}, {"title": "Reminders", "records": reminders}],
        [
            {"label": "Edit Settings" if setting else "Add Settings", "url": reverse("settings_edit")},
            {"label": "Add Reminder", "url": reverse("model_form", args=["reminders"])},
        ],
    )


def _profile_form_page(request, form_class, title, redirect_name):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response
    profile = _profile_for_user(user)
    form = form_class(request.POST or None, instance=profile)
    if request.method == "POST":
        if form.is_valid():
            record = form.save(commit=False)
            record.user_id = user
            record.updated_at = timezone.localdate()
            record.save()
            messages.success(request, f"{title} saved successfully.")
            return redirect(redirect_name)
        messages.error(request, "Please correct the errors below.")
    return render(request, "module_form.html", {"form": form, "title": title, "cancel_url": reverse(redirect_name)})


def ProfileFormPage(request):
    return _profile_form_page(request, UserProfileForm, "Profile information", "profile")


def GoalsFormPage(request):
    return _profile_form_page(request, GoalsForm, "Goals", "goals")


def SettingsFormPage(request):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response
    setting = UserSetting.objects.filter(user_id=user).first()
    form = SettingsForm(request.POST or None, instance=setting)
    if request.method == "POST":
        if form.is_valid():
            record = form.save(commit=False)
            record.user_id = user
            record.save()
            messages.success(request, "Settings saved successfully.")
            return redirect("settings")
        messages.error(request, "Please correct the errors below.")
    return render(request, "module_form.html", {"form": form, "title": "Settings", "cancel_url": reverse("settings")})


def Register(request):
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            last_user_id = Users.objects.aggregate(max_id=Max("user_id"))["max_id"] or 0
            today = timezone.localdate()
            user = Users.objects.create(
                user_id=last_user_id + 1,
                full_name=form.cleaned_data["full_name"],
                email=form.cleaned_data["email"],
                phone=form.cleaned_data["phone"],
                password_hash=make_password(form.cleaned_data["password"]),
                created_at=today,
                last_login=today,
            )
        request.session["user_id"] = user.pk
        return redirect("onboarding")

    return render(request, "register.html", {"form": form})


def ModelForms(request):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response

    forms = [
        {"slug": slug, "title": title, "admin_only": slug in {"achievements", "user-achievements"}}
        for slug, (title, _) in MODEL_FORM_REGISTRY.items()
    ]
    return render(request, "model_forms.html", {"forms": forms})


def ModelFormPage(request, model_slug):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response

    if model_slug not in MODEL_FORM_REGISTRY:
        raise Http404("Form not found")

    title, form_class = MODEL_FORM_REGISTRY[model_slug]
    if model_slug in {"achievements", "user-achievements"}:
        admin_model = "achievement" if model_slug == "achievements" else "userachievement"
        return redirect(f"admin:DietApp_{admin_model}_add")

    instance = user if model_slug == "users" else None
    if model_slug == "user-profiles":
        instance = _profile_for_user(user)
    elif model_slug == "user-settings":
        instance = UserSetting.objects.filter(user_id=user).first()

    form_kwargs = {"instance": instance} if instance else {}
    if request.method == "POST":
        form_kwargs.update({"data": request.POST, "files": request.FILES})
    form = form_class(**form_kwargs)

    if model_slug == "users":
        form.fields = {
            name: field
            for name, field in form.fields.items()
            if name not in {"password", "profile_image", "created_at", "last_login", "user_id", "is_active"}
        }

    if model_slug == "users":
        for field_name in ("user_id", "created_at", "last_login"):
            if field_name in form.fields:
                form.fields[field_name].disabled = True
    elif "user_id" in form.fields:
        user_field = form.fields["user_id"]
        if hasattr(user_field, "queryset"):
            user_field.queryset = Users.objects.filter(pk=user.pk)
        form.initial["user_id"] = user
        if model_slug == "user-settings":
            user_field.disabled = True

    if model_slug in {"food-logs", "recipe-ingredients"} and "food_id" in form.fields:
        form.fields["food_id"].queryset = Food.objects.filter(user_id=user)
        if model_slug == "food-logs" and request.method == "GET":
            selected_food = Food.objects.filter(
                user_id=user, pk=request.GET.get("food_id")
            ).first()
            if selected_food:
                form.initial["food_id"] = selected_food
    if model_slug in {"meal-plans", "recipe-ingredients", "favorite-recipes"} and "recipe_id" in form.fields:
        recipes = Recipe.objects.filter(user_id=user)
        if model_slug in {"meal-plans", "favorite-recipes"}:
            recipes = Recipe.objects.filter(Q(user_id=user) | Q(is_public=True))
        form.fields["recipe_id"].queryset = recipes
        if model_slug == "meal-plans" and request.method == "GET":
            selected_recipe = recipes.filter(pk=request.GET.get("recipe_id")).first()
            if selected_recipe:
                form.initial["recipe_id"] = selected_recipe
    if model_slug == "recipes":
        form.fields.pop("is_public", None)
        form.instance.is_public = False

    primary_key = form._meta.model._meta.pk
    if (
        model_slug not in {"users", "user-settings"}
        and not primary_key.auto_created
        and primary_key.name in form.fields
    ):
        form.fields[primary_key.name].required = False

    if request.method == "POST" and form.is_valid():
        record = form.save(commit=False)
        if model_slug != "users" and hasattr(record, "user_id"):
            record.user_id = user
        if isinstance(record, UserProfile):
            record.updated_at = timezone.localdate()
        if model_slug == "recipes":
            record.is_public = False
        if (
            model_slug not in {"users", "user-settings"}
            and not primary_key.auto_created
            and not record.pk
        ):
            max_id = (
                form._meta.model.objects.aggregate(max_id=Max(primary_key.name))["max_id"]
                or 0
            )
            record.pk = max_id + 1
        record.save()
        form.save_m2m()
        messages.success(request, f"{title} saved successfully.")
        detail_routes = {
            "user-profiles": "profile",
            "user-settings": "settings",
            "user-achievements": "achievements",
            "weight-logs": "profile",
            "food-logs": "diet",
            "foods": "diet",
            "water-logs": "diet",
            "meal-plans": "diet",
            "recipes": "diet",
            "recipe-ingredients": "diet",
            "favorite-recipes": "diet",
            "reminders": "settings",
        }
        if model_slug in detail_routes:
            return redirect(detail_routes[model_slug])
        return redirect("model_form", model_slug=model_slug)

    if request.method == "POST" and not form.is_valid():
        messages.error(request, "Please correct the errors below.")

    cancel_routes = {
        "user-profiles": "profile",
        "user-settings": "settings",
        "weight-logs": "profile",
        "food-logs": "diet",
        "foods": "diet",
        "water-logs": "diet",
        "meal-plans": "diet",
        "recipes": "diet",
        "recipe-ingredients": "diet",
        "favorite-recipes": "diet",
        "reminders": "settings",
    }
    return render(
        request,
        "model_form.html",
        {
            "form": form,
            "title": title,
            "model_slug": model_slug,
            "cancel_url": reverse(cancel_routes[model_slug]) if model_slug in cancel_routes else reverse("model_forms"),
        },
    )


def ModelRecordEditPage(request, model_slug, record_id):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response

    editable_models = {
        "weight-logs", "foods", "food-logs", "water-logs", "recipes",
        "recipe-ingredients", "meal-plans", "reminders", "favorite-recipes",
    }
    if model_slug not in editable_models:
        raise Http404("Record editing is not available")

    title, form_class = MODEL_FORM_REGISTRY[model_slug]
    model = form_class._meta.model
    if model_slug == "recipe-ingredients":
        instance = get_object_or_404(model, pk=record_id, recipe_id__user_id=user)
    else:
        instance = get_object_or_404(model, pk=record_id, user_id=user)
    form = form_class(request.POST or None, instance=instance)
    form.fields.pop("user_id", None)
    primary_key_name = model._meta.pk.name
    form.fields.pop(primary_key_name, None)
    if model_slug == "food-logs" and "food_id" in form.fields:
        form.fields["food_id"].queryset = Food.objects.filter(user_id=user)
    if model_slug == "meal-plans" and "recipe_id" in form.fields:
        form.fields["recipe_id"].queryset = Recipe.objects.filter(Q(user_id=user) | Q(is_public=True))
    if model_slug == "recipe-ingredients":
        if "recipe_id" in form.fields:
            form.fields["recipe_id"].queryset = Recipe.objects.filter(user_id=user)
        if "food_id" in form.fields:
            form.fields["food_id"].queryset = Food.objects.filter(user_id=user)

    if request.method == "POST":
        if form.is_valid():
            record = form.save(commit=False)
            if hasattr(record, "user_id"):
                record.user_id = user
            elif model_slug == "recipe-ingredients" and record.recipe_id.user_id != user:
                raise Http404("Recipe is not editable")
            record.save()
            messages.success(request, f"{title} updated successfully.")
            return redirect("profile" if model_slug == "weight-logs" else "settings" if model_slug == "reminders" else "diet")
        messages.error(request, "Please correct the errors below.")

    return render(
        request,
        "module_form.html",
        {
            "form": form,
            "title": f"Edit {title}",
            "cancel_url": reverse("profile" if model_slug == "weight-logs" else "settings" if model_slug == "reminders" else "diet"),
        },
    )


@require_POST
def DeleteFood(request, record_id):
    user, redirect_response = _get_logged_in_user(request)
    if redirect_response:
        return redirect_response

    food = get_object_or_404(Food, pk=record_id, user_id=user)
    try:
        food.delete()
    except RestrictedError:
        messages.error(request, "This food is used by a food diary entry and cannot be deleted yet.")
    else:
        messages.success(request, "Food removed successfully.")
    return redirect("food_log")


ADMIN_CATALOGS = {
    "foods": {
        "title": "Food Management",
        "model": Food,
        "form": AdminFoodForm,
        "permission": "food",
        "list_fields": ("name", "brand", "serving_size", "serving_unit", "calories", "protein", "carbs", "fat"),
        "order": ("name",),
    },
    "recipes": {
        "title": "Recipes",
        "model": Recipe,
        "form": AdminRecipeForm,
        "permission": "recipe",
        "list_fields": ("name", "servings", "calories_per_serving", "total_time_minutes", "is_public"),
        "order": ("name",),
    },
    "diet-plans": {
        "title": "Diet Plans",
        "model": MealPlan,
        "form": AdminMealPlanForm,
        "permission": "mealplan",
        "list_fields": ("plan_date", "user_id", "meal_type", "recipe_id", "custom_meal_name"),
        "order": ("-plan_date",),
    },
}


def _admin_access(request, permission):
    if not request.user.is_authenticated:
        if request.session.get("user_id"):
            raise PermissionDenied
        return redirect("login")
    if not (request.user.is_superuser or request.user.has_perm(permission)):
        raise PermissionDenied
    return None


def _admin_record_value(record, field_name):
    value = getattr(record, field_name)
    display = getattr(record, f"get_{field_name}_display", None)
    if display:
        return display()
    if value is None or value == "":
        return "Not provided"
    if hasattr(value, "full_name"):
        return value.full_name
    if hasattr(value, "name"):
        return value.name
    return value


def AdminDashboard(request):
    denied = _admin_access(request, "DietApp.view_users")
    if denied:
        return denied
    today = timezone.localdate()
    six_months_ago = today.replace(day=1)
    for _ in range(5):
        six_months_ago = (six_months_ago.replace(day=1) - timedelta(days=1)).replace(day=1)
    month_counts = []
    month_cursor = six_months_ago
    for _ in range(6):
        next_month = (month_cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        month_counts.append({
            "label": month_cursor.strftime("%b"),
            "count": Users.objects.filter(created_at__gte=month_cursor, created_at__lt=next_month).count(),
        })
        month_cursor = next_month
    max_registrations = max((item["count"] for item in month_counts), default=0)
    for item in month_counts:
        item["height"] = round(item["count"] / max_registrations * 100) if max_registrations else 0
    context = {
        "stats": [
            {"label": "Registered users", "value": Users.objects.count(), "url": reverse("admin_users")},
            {"label": "Foods", "value": Food.objects.count(), "url": reverse("admin_catalog", args=["foods"])},
            {"label": "Recipes", "value": Recipe.objects.count(), "url": reverse("admin_catalog", args=["recipes"])},
            {"label": "Diet plans", "value": MealPlan.objects.count(), "url": reverse("admin_catalog", args=["diet-plans"])},
            {"label": "Awaiting support", "value": SupportQuestion.objects.filter(answer="").count(), "url": reverse("admin_support")},
        ],
        "recent_users": Users.objects.order_by("-created_at", "-pk")[:6],
        "recent_questions": SupportQuestion.objects.select_related("user").order_by("-created_at")[:6],
        "recent_foods": Food.objects.select_related("user_id").order_by("-pk")[:5],
        "recent_recipes": Recipe.objects.order_by("-pk")[:5],
        "month_counts": month_counts,
        "max_registrations": max_registrations,
        "recent_payments": SubscriptionPayment.objects.select_related("user").filter(status="successful")[:5],
        "unseen_payment_count": SubscriptionPayment.objects.filter(
            status="successful", admin_viewed_at__isnull=True
        ).count(),
    }
    return render(request, "admin/dashboard.html", context)


def AdminUsers(request):
    denied = _admin_access(request, "DietApp.view_users")
    if denied:
        return denied
    query = request.GET.get("q", "").strip()
    users = Users.objects.all().order_by("-created_at", "-pk")
    if query:
        users = users.filter(Q(full_name__icontains=query) | Q(email__icontains=query) | Q(phone__icontains=query))
    from django.core.paginator import Paginator
    page = Paginator(users, 25).get_page(request.GET.get("page"))
    admin_emails = {
        email.casefold()
        for email in get_user_model()._default_manager.filter(
            email__in=[member.email for member in page.object_list], is_staff=True
        ).values_list("email", flat=True)
    }
    for member in page.object_list:
        member.admin_role = "Administrator" if member.email.casefold() in admin_emails else "Member"
    return render(request, "admin/users.html", {"page": page, "query": query})


def AdminPayments(request):
    denied = _admin_access(request, "DietApp.view_users")
    if denied:
        return denied
    payments = SubscriptionPayment.objects.select_related("user")[:100]
    unseen_ids = list(
        SubscriptionPayment.objects.filter(
            status="successful", admin_viewed_at__isnull=True
        ).values_list("pk", flat=True)
    )
    if unseen_ids:
        SubscriptionPayment.objects.filter(pk__in=unseen_ids).update(
            admin_viewed_at=timezone.now()
        )
    return render(
        request,
        "admin/payments.html",
        {
            "payments": payments,
            "unseen_payment_count": len(unseen_ids),
        },
    )


def AdminUserDetail(request, record_id):
    denied = _admin_access(request, "DietApp.view_users")
    if denied:
        return denied
    user = get_object_or_404(Users, pk=record_id)
    linked_auth_user = get_user_model()._default_manager.filter(email__iexact=user.email).first()
    role = "Administrator" if linked_auth_user and linked_auth_user.is_staff else "Member"
    return render(request, "admin/user_detail.html", {"managed_user": user, "role": role})


def AdminUserFormPage(request, record_id=None):
    permission = "DietApp.add_users" if record_id is None else "DietApp.change_users"
    denied = _admin_access(request, permission)
    if denied:
        return denied
    instance = get_object_or_404(Users, pk=record_id) if record_id else None
    form = AdminUserForm(request.POST or None, request.FILES or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        managed_user = form.save(commit=False)
        if instance is None:
            managed_user.user_id = (Users.objects.aggregate(max_id=Max("user_id"))["max_id"] or 0) + 1
            managed_user.created_at = timezone.localdate()
            managed_user.last_login = timezone.localdate()
        managed_user.save()
        messages.success(request, "User account saved.")
        return redirect("admin_user_detail", record_id=managed_user.pk)
    return render(request, "admin/form.html", {"form": form, "title": "Edit user" if instance else "Add user", "cancel_url": reverse("admin_users")})


def AdminUserPasswordReset(request, record_id):
    denied = _admin_access(request, "DietApp.change_users")
    if denied:
        return denied
    managed_user = get_object_or_404(Users, pk=record_id)
    form = PasswordResetConfirmForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        new_password = form.cleaned_data["password"]
        managed_user.password_hash = make_password(new_password)
        managed_user.save(update_fields=["password_hash"])
        linked_auth_user = get_user_model()._default_manager.filter(
            email__iexact=managed_user.email
        ).first()
        if linked_auth_user:
            linked_auth_user.set_password(new_password)
            linked_auth_user.save(update_fields=["password"])
        messages.success(request, "User password reset successfully.")
        return redirect("admin_user_detail", record_id=managed_user.pk)
    return render(
        request,
        "admin/form.html",
        {
            "form": form,
            "title": f"Reset password for {managed_user.full_name}",
            "cancel_url": reverse("admin_user_detail", args=[managed_user.pk]),
        },
    )


@require_POST
def AdminUserDelete(request, record_id):
    denied = _admin_access(request, "DietApp.delete_users")
    if denied:
        return denied
    managed_user = get_object_or_404(Users, pk=record_id)
    if request.POST.get("confirm") != "yes":
        return render(request, "admin/confirm_delete.html", {"object_label": managed_user.full_name, "cancel_url": reverse("admin_user_detail", args=[record_id])})
    try:
        managed_user.delete()
    except RestrictedError:
        messages.error(request, "This account still owns records and cannot be deleted. Deactivate it instead.")
        return redirect("admin_user_detail", record_id=record_id)
    messages.success(request, "User account deleted.")
    return redirect("admin_users")


def AdminCatalog(request, catalog_slug):
    config = ADMIN_CATALOGS.get(catalog_slug)
    if not config:
        raise Http404("Management section not found")
    denied = _admin_access(request, f"DietApp.view_{config['permission']}")
    if denied:
        return denied
    query = request.GET.get("q", "").strip()
    queryset = config["model"].objects.all().order_by(*config["order"])
    if query:
        searchable = [field.name for field in config["model"]._meta.fields if isinstance(field, (models.CharField, models.TextField))]
        filters = Q()
        for field_name in searchable:
            filters |= Q(**{f"{field_name}__icontains": query})
        if searchable:
            queryset = queryset.filter(filters)
    from django.core.paginator import Paginator
    page = Paginator(queryset, 25).get_page(request.GET.get("page"))
    rows = [{"pk": record.pk, "values": [_admin_record_value(record, field) for field in config["list_fields"]]} for record in page]
    labels = [config["model"]._meta.get_field(field).verbose_name.title() for field in config["list_fields"]]
    return render(request, "admin/catalog.html", {
        "title": config["title"], "catalog_slug": catalog_slug, "page": page,
        "rows": rows, "labels": labels, "query": query,
        "can_add": request.user.is_superuser or request.user.has_perm(f"DietApp.add_{config['permission']}"),
        "can_change": request.user.is_superuser or request.user.has_perm(f"DietApp.change_{config['permission']}"),
        "can_delete": request.user.is_superuser or request.user.has_perm(f"DietApp.delete_{config['permission']}"),
    })


def AdminCatalogForm(request, catalog_slug, record_id=None):
    config = ADMIN_CATALOGS.get(catalog_slug)
    if not config:
        raise Http404("Management section not found")
    action = "add" if record_id is None else "change"
    denied = _admin_access(request, f"DietApp.{action}_{config['permission']}")
    if denied:
        return denied
    instance = get_object_or_404(config["model"], pk=record_id) if record_id else None
    form = config["form"](request.POST or None, request.FILES or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        record = form.save(commit=False)
        primary_key = config["model"]._meta.pk
        if not record.pk:
            record.pk = (config["model"].objects.aggregate(max_id=Max(primary_key.name))["max_id"] or 0) + 1
        record.save()
        form.save_m2m()
        messages.success(request, f"{config['title']} record saved.")
        return redirect("admin_catalog", catalog_slug=catalog_slug)
    return render(request, "admin/form.html", {"form": form, "title": f"Edit {config['title'].rstrip('s')}" if instance else f"Add {config['title'].rstrip('s')}", "cancel_url": reverse("admin_catalog", args=[catalog_slug])})


@require_POST
def AdminCatalogDelete(request, catalog_slug, record_id):
    config = ADMIN_CATALOGS.get(catalog_slug)
    if not config:
        raise Http404("Management section not found")
    denied = _admin_access(request, f"DietApp.delete_{config['permission']}")
    if denied:
        return denied
    record = get_object_or_404(config["model"], pk=record_id)
    if request.POST.get("confirm") != "yes":
        return render(request, "admin/confirm_delete.html", {"object_label": str(record), "cancel_url": reverse("admin_catalog", args=[catalog_slug])})
    try:
        record.delete()
    except RestrictedError:
        messages.error(request, "This record is referenced by other data and cannot be deleted.")
    else:
        messages.success(request, "Record deleted.")
    return redirect("admin_catalog", catalog_slug=catalog_slug)


def AdminSupport(request):
    denied = _admin_access(request, "DietApp.view_supportquestion")
    if denied:
        return denied
    questions = SupportQuestion.objects.select_related("user").order_by("answer", "-created_at")
    return render(request, "admin/support.html", {"questions": questions})


def AdminSupportAnswer(request, record_id):
    denied = _admin_access(request, "DietApp.change_supportquestion")
    if denied:
        return denied
    question = get_object_or_404(SupportQuestion.objects.select_related("user"), pk=record_id)
    form = AdminSupportAnswerForm(request.POST or None, instance=question)
    if request.method == "POST" and form.is_valid():
        form.save()
        SupportQuestion.objects.filter(question_key=question.question_key).exclude(pk=question.pk).update(answer=question.answer, answer_viewed_at=None)
        messages.success(request, "Support response saved and shared with users who asked the same question.")
        return redirect("admin_support")
    return render(request, "admin/support_detail.html", {"question": question, "form": form})


def AdminReports(request):
    denied = _admin_access(request, "DietApp.view_users")
    if denied:
        return denied
    return render(request, "admin/reports.html", {
        "users_count": Users.objects.count(),
        "active_users": Users.objects.filter(is_active=True).count(),
        "food_count": Food.objects.count(),
        "recipe_count": Recipe.objects.count(),
        "plan_count": MealPlan.objects.count(),
        "support_pending": SupportQuestion.objects.filter(answer="").count(),
        "support_answered": SupportQuestion.objects.exclude(answer="").count(),
    })
