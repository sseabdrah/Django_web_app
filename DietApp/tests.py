from datetime import date, time, timedelta
from urllib.parse import urlsplit
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse

from DietApp.ai_support import generate_diet_ai_answer
from DietApp.models import Achievement, Food, FoodLog, Recipe, SubscriptionPayment, SupportFeedback, SupportQuestion, UserAchievement, UserProfile, Users, WaterLog, WeightLog
from DietApp.views import MODEL_FORM_REGISTRY, _add_months, _trial_end_date

# Create your tests here.
@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class LoginTests(TestCase):
	def setUp(self):
		self.user = Users.objects.create(
			user_id=1,
			full_name="Test User",
			email="test@example.com",
			password_hash="secret",
			phone="555-0100",
			created_at=date.today(),
			last_login=date.today(),
		)

	def test_valid_login_displays_onboarding_then_dashboard(self):
		login_page = self.client.get("/login/")
		self.assertContains(login_page, 'type="radio"')
		self.assertContains(login_page, "Normal user")
		self.assertContains(login_page, "Administrator")
		self.user.last_login = date(2000, 1, 1)
		self.user.save(update_fields=["last_login"])

		response = self.client.post(
			"/login/", {"email": "test@example.com", "password": "secret"}
		)

		self.assertRedirects(response, reverse("onboarding"))
		self.user.refresh_from_db()
		self.assertTrue(check_password("secret", self.user.password_hash))
		self.assertEqual(self.user.last_login, timezone.localdate())
		onboarding = self.client.get(reverse("onboarding"))
		self.assertContains(onboarding, "Welcome to Diet Services")
		self.assertContains(onboarding, "A fresh start")
		self.assertContains(onboarding, "fresh-fruit")
		self.assertContains(onboarding, "prefers-reduced-motion")
		self.assertRedirects(
			self.client.post(reverse("onboarding"), {"destination": "dashboard"}),
			reverse("dashboard"),
		)
		self.user.refresh_from_db()
		self.assertTrue(self.user.onboarding_complete)
		dashboard = self.client.get("/dashboard/")
		self.assertContains(dashboard, "Welcome, Test User!")
		self.assertContains(dashboard, "What would you like to visit?")
		self.assertContains(dashboard, "Account Details")
		self.assertContains(dashboard, "Food Log")
		self.assertEqual(len(dashboard.context["modules"]), 6)
		self.assertNotContains(dashboard, "Edit Account Details")
		self.assertNotContains(dashboard, "Edit Profile")
		self.assertNotContains(dashboard, "Add Food")
		self.assertNotContains(dashboard, "All Nutrition Forms")
		self.assertNotContains(dashboard, "password_hash")
		self.assertNotContains(dashboard, self.user.password_hash)
		self.assertContains(dashboard, "Calories today")
		self.assertContains(dashboard, "Water today")
		self.assertEqual(dashboard.context["daily_summary"]["calories"], 0)

	def test_completed_onboarding_skips_welcome_on_later_login(self):
		self.user.onboarding_complete = True
		self.user.save(update_fields=["onboarding_complete"])
		response = self.client.post(
			reverse("login"), {"email": self.user.email, "password": "secret"}
		)
		self.assertRedirects(response, reverse("dashboard"))

	def test_dashboard_summarizes_today_against_profile_targets(self):
		self.client.post(
			"/login/", {"email": self.user.email, "password": "secret"}
		)
		today = timezone.localdate()
		UserProfile.objects.create(
			user_id=self.user,
			daily_calorie_target=2000,
			daily_water_target=2000,
			updated_at=today,
		)
		food = Food.objects.create(
			food_id=1,
			name="Oats",
			serving_size=100,
			serving_unit="g",
			calories=150,
			protein=5,
			carbs=27,
			fat=3,
			user_id=self.user,
		)
		FoodLog.objects.create(
			food_log_id=1,
			user_id=self.user,
			food_id=food,
			meal_type="breakfast",
			quantity=1,
			serving_unit="g",
			calories_consumed=350,
			protein_consumed=12,
			carbs_consumed=60,
			fat_consumed=7,
			log_date=today,
			log_time=time(8, 0),
		)
		WaterLog.objects.create(
			water_log_id=1,
			user_id=self.user,
			amount_ml=500,
			log_date=today,
			log_time=time(9, 0),
		)

		response = self.client.get("/dashboard/")
		summary = response.context["daily_summary"]

		self.assertEqual(summary["calories"], 350)
		self.assertEqual(summary["calories_progress"], 18)
		self.assertEqual(summary["protein"], 12)
		self.assertEqual(summary["water_ml"], 500)
		self.assertEqual(summary["water_progress"], 25)

	def test_dashboard_counts_consecutive_activity_streak(self):
		self.client.post("/login/", {"email": self.user.email, "password": "secret"})
		today = timezone.localdate()
		for offset in range(3):
			WeightLog.objects.create(
				weight_log_id=offset + 1,
				user_id=self.user,
				weight_kg=70,
				log_date=today - timedelta(days=offset),
			)

		response = self.client.get(reverse("dashboard"))

		self.assertEqual(response.context["streak"]["current"], 3)
		self.assertEqual(response.context["streak"]["best"], 3)
		self.assertEqual(len(response.context["streak"]["calendar"]), 28)

	@override_settings(DIETAPP_ADMIN_EMAIL="test@example.com")
	def test_admin_account_login_syncs_same_identity_and_credentials(self):
		response = self.client.post(
			"/login/", {"role": "admin", "email": "test@example.com", "password": "secret"}
		)

		self.assertRedirects(response, reverse("admin_dashboard"))
		admin_user = get_user_model().objects.get(email="test@example.com")
		self.assertTrue(admin_user.is_staff)
		self.assertTrue(admin_user.is_superuser)
		self.assertTrue(admin_user.check_password("secret"))
		self.assertEqual(admin_user.first_name, "Test")
		self.assertEqual(admin_user.last_name, "User")
		self.assertEqual(self.client.session["user_id"], self.user.pk)
		self.assertEqual(int(self.client.session["_auth_user_id"]), admin_user.pk)
		self.assertEqual(self.client.get(reverse("admin_dashboard")).status_code, 200)
		self.assertNotContains(self.client.get(reverse("admin_dashboard")), "Calories today")

	def test_native_django_admin_can_log_in_to_website(self):
		admin_user = get_user_model().objects.create_superuser(
			username="site-admin", email="admin@example.com", password="admin-secret"
		)

		response = self.client.post(
			"/login/", {"role": "admin", "email": admin_user.email, "password": "admin-secret"}
		)

		self.assertRedirects(response, reverse("admin_dashboard"))
		self.assertEqual(int(self.client.session["_auth_user_id"]), admin_user.pk)
		linked_user = Users.objects.get(email=admin_user.email)
		self.assertEqual(self.client.session["user_id"], linked_user.pk)
		dashboard = self.client.get(reverse("admin_dashboard"))
		self.assertContains(dashboard, "Platform overview")
		self.assertContains(dashboard, "Recent registrations")
		self.assertNotContains(dashboard, "Calories today")

	def test_normal_user_cannot_log_in_using_admin_role(self):
		response = self.client.post(
			"/login/", {"role": "admin", "email": self.user.email, "password": "secret"}
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Email or password is incorrect.")
		self.assertNotIn("user_id", self.client.session)
		self.client.post("/login/", {"email": self.user.email, "password": "secret"})
		self.assertNotContains(
			self.client.get("/dashboard/"),
			"Diet Administration: Support questions",
		)

	def test_logout_clears_session_and_requires_sign_in(self):
		self.client.post("/login/", {"email": "test@example.com", "password": "secret"})

		response = self.client.post("/logout/")

		self.assertRedirects(response, "/login/")
		self.assertRedirects(self.client.get("/dashboard/"), "/login/")

	@override_settings(DIETAPP_ADMIN_EMAIL="test@example.com")
	def test_admin_logout_then_normal_login_uses_fresh_role_session(self):
		admin_response = self.client.post(
			reverse("login"), {"role": "admin", "email": self.user.email, "password": "secret"}
		)
		self.assertRedirects(admin_response, reverse("admin_dashboard"))
		self.client.post(reverse("logout"))
		self.assertNotIn("user_id", self.client.session)
		member = Users.objects.create(
			user_id=2, full_name="Second User", email="second@example.com",
			password_hash="secret", phone="555-0101", created_at=date.today(),
			last_login=date.today(),
		)
		normal_response = self.client.post(
			reverse("login"), {"role": "user", "email": member.email, "password": "secret"}
		)
		self.assertRedirects(normal_response, reverse("onboarding"))
		self.assertNotIn("_auth_user_id", self.client.session)
		self.assertEqual(self.client.session["user_id"], member.pk)

	def test_normal_user_cannot_access_admin_management_routes(self):
		self.client.post(reverse("login"), {"email": self.user.email, "password": "secret"})
		for route in ("admin_dashboard", "admin_users", "admin_support", "admin_reports"):
			with self.subTest(route=route):
				self.assertEqual(self.client.get(reverse(route)).status_code, 403)
		self.assertEqual(self.client.get(reverse("admin_catalog", args=["foods"])).status_code, 403)

	def test_invalid_login_shows_error(self):
		response = self.client.post(
			"/login/", {"email": "test@example.com", "password": "wrong"}
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Email or password is incorrect.")

	@override_settings(MAILERS={"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}})
	def test_password_reset_link_updates_password_and_cannot_be_reused(self):
		response = self.client.post(
			"/password-reset/", {"email": self.user.email}
		)
		self.assertContains(response, "a reset link has been sent")
		self.assertEqual(len(mail.outbox), 1)
		reset_path = urlsplit(mail.outbox[0].body.splitlines()[2]).path

		reset_page = self.client.get(reset_path)
		self.assertEqual(reset_page.status_code, 200)
		response = self.client.post(
			reset_path,
			{"password": "new-secure-pass", "confirm_password": "new-secure-pass"},
		)
		self.assertRedirects(response, "/login/")
		self.user.refresh_from_db()
		self.assertTrue(check_password("new-secure-pass", self.user.password_hash))
		self.assertContains(self.client.get(reset_path), "Reset link unavailable")


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class RegisterTests(TestCase):
	def test_register_creates_account_and_displays_onboarding(self):
		response = self.client.post(
			"/register/",
			{
				"full_name": "New User",
				"email": "new@example.com",
				"phone": "555-0101",
				"password": "secure-pass",
				"confirm_password": "secure-pass",
			},
		)

		self.assertRedirects(response, reverse("onboarding"))
		user = Users.objects.get(email="new@example.com")
		self.assertTrue(check_password("secure-pass", user.password_hash))
		self.assertContains(self.client.get(reverse("onboarding")), "New User")

	def test_register_rejects_mismatched_passwords(self):
		response = self.client.post(
			"/register/",
			{
				"full_name": "New User",
				"email": "new@example.com",
				"phone": "555-0101",
				"password": "secure-pass",
				"confirm_password": "different-pass",
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Passwords do not match.")
		self.assertFalse(Users.objects.filter(email="new@example.com").exists())


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class AdminUserManagementTests(TestCase):
	def setUp(self):
		self.admin = get_user_model().objects.create_superuser(
			username="management-admin",
			email="management-admin@example.com",
			password="admin-password",
		)
		self.client.force_login(self.admin)

	def test_admin_can_add_reset_and_remove_a_user(self):
		response = self.client.post(
			reverse("admin_user_add"),
			{
				"full_name": "Managed Member",
				"email": "managed@example.com",
				"phone": "555-0199",
				"is_active": "on",
				"password": "initial-password",
			},
		)
		managed_user = Users.objects.get(email="managed@example.com")
		self.assertRedirects(
			response,
			reverse("admin_user_detail", args=[managed_user.pk]),
		)
		self.assertContains(
			self.client.get(reverse("admin_user_detail", args=[managed_user.pk])),
			"Reset password",
		)

		response = self.client.post(
			reverse("admin_user_password_reset", args=[managed_user.pk]),
			{"password": "replacement-password", "confirm_password": "replacement-password"},
		)
		self.assertRedirects(response, reverse("admin_user_detail", args=[managed_user.pk]))
		managed_user.refresh_from_db()
		self.assertTrue(check_password("replacement-password", managed_user.password_hash))

		response = self.client.post(
			reverse("admin_user_delete", args=[managed_user.pk]), {"confirm": "yes"}
		)
		self.assertRedirects(response, reverse("admin_users"))
		self.assertFalse(Users.objects.filter(pk=managed_user.pk).exists())

	def test_password_reset_updates_linked_django_staff_login(self):
		linked_user = get_user_model().objects.create_user(
			username="linked-member",
			email="linked@example.com",
			password="old-password",
			is_staff=True,
		)
		managed_user = Users.objects.create(
			user_id=1,
			full_name="Linked Member",
			email="linked@example.com",
			password_hash="old-password",
			phone="555-0101",
			created_at=date.today(),
			last_login=date.today(),
		)

		response = self.client.post(
			reverse("admin_user_password_reset", args=[managed_user.pk]),
			{"password": "new-linked-password", "confirm_password": "new-linked-password"},
		)

		self.assertRedirects(response, reverse("admin_user_detail", args=[managed_user.pk]))
		linked_user.refresh_from_db()
		self.assertTrue(linked_user.check_password("new-linked-password"))

	def test_non_admin_cannot_reset_user_password(self):
		managed_user = Users.objects.create(
			user_id=1,
			full_name="Member",
			email="member@example.com",
			password_hash="old-password",
			phone="555-0101",
			created_at=date.today(),
			last_login=date.today(),
		)
		self.client.logout()

		response = self.client.get(
			reverse("admin_user_password_reset", args=[managed_user.pk])
		)

		self.assertEqual(response.status_code, 302)
		self.assertRedirects(response, reverse("login"))


class SubscriptionPageTests(TestCase):
	def setUp(self):
		self.user = Users.objects.create(
			user_id=1,
			full_name="Trial Member",
			email="trial@example.com",
			password_hash="unused",
			phone="555-0101",
			created_at=timezone.localdate(),
			last_login=timezone.localdate(),
		)
		session = self.client.session
		session["user_id"] = self.user.pk
		session.save()

	def test_billing_page_displays_trial_and_selected_plans(self):
		response = self.client.get(reverse("subscription"))

		self.assertContains(response, "Your free month is active")
		self.assertContains(response, "UGX 30,000")
		self.assertContains(response, "UGX 150,000")
		self.assertContains(response, "Airtel Money")
		self.assertContains(response, "MTN Mobile Money")
		self.assertContains(response, "Mobile Money payment is not connected yet")
		self.assertContains(response, 'type="radio" name="network" value="AIRTEL"')
		self.assertContains(response, 'type="radio" name="network" value="MTN"')
		self.assertContains(response, "Frequently asked questions")
		self.assertContains(response, "Where do I enter my Mobile Money PIN?")
		self.assertContains(response, 'id="pay-button" type="submit" hidden>Pay</button>')
		self.assertContains(response, "updatePayButton")
		self.assertNotContains(response, "Flutterwave")

	def test_pay_without_mobile_money_connection_sends_no_request(self):
		response = self.client.post(
			reverse("subscription"),
			{"plan": "monthly", "network": "AIRTEL", "phone_number": "0772 123456"},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Mobile Money is not connected yet, so no payment request was sent.")
		self.assertEqual(SubscriptionPayment.objects.count(), 0)

	@override_settings(FLW_SECRET_KEY="test-secret", FLW_SECRET_HASH="test-hash")
	def test_enabled_checkout_asks_for_final_confirmation(self):
		response = self.client.get(reverse("subscription"))

		self.assertContains(response, ">Pay</button>")
		self.assertContains(response, "window.confirm")
		self.assertContains(response, "enter your PIN there to approve")

	def test_trial_period_uses_one_calendar_month(self):
		self.user.created_at = date(2026, 1, 31)
		self.user.save(update_fields=["created_at"])

		response = self.client.get(reverse("subscription"))

		self.assertEqual(response.context["trial_ends_on"], date(2026, 2, 28))

	@override_settings(FLW_SECRET_KEY="test-secret", FLW_SECRET_HASH="test-hash")
	def test_checkout_initiates_provider_request_without_collecting_pin(self):
		with patch(
			"DietApp.views.initiate_uganda_mobile_money",
			return_value="https://checkout.flutterwave.com/authorize",
		) as initiate:
			response = self.client.post(
				reverse("subscription"),
				{"plan": "monthly", "network": "AIRTEL", "phone_number": "0772 123456"},
			)

		self.assertRedirects(
			response,
			"https://checkout.flutterwave.com/authorize",
			fetch_redirect_response=False,
		)
		payment = SubscriptionPayment.objects.get(user=self.user)
		self.assertEqual(payment.amount, 30000)
		self.assertEqual(payment.phone_number, "256772123456")
		self.assertEqual(payment.status, "pending")
		initiate.assert_called_once()
		self.assertNotIn("pin", initiate.call_args.args[0].__dict__)

	def test_payment_return_only_extends_access_after_provider_verification(self):
		payment = SubscriptionPayment.objects.create(
			user=self.user,
			tx_ref="test-payment-reference",
			plan="monthly",
			network="MTN",
			phone_number="256772123456",
			amount=30000,
		)
		provider_data = {
			"id": 12345,
			"tx_ref": payment.tx_ref,
			"status": "successful",
			"currency": "UGX",
			"amount": 30000,
			"flw_ref": "flw-reference",
		}
		with patch("DietApp.views.verify_uganda_mobile_money", return_value=provider_data):
			with patch("DietApp.views.send_mail", return_value=1) as send_mail:
				with self.captureOnCommitCallbacks(execute=True):
					response = self.client.get(
						reverse("subscription_return"),
						{"tx_ref": payment.tx_ref, "transaction_id": "12345"},
					)

		self.assertRedirects(response, reverse("subscription"))
		payment.refresh_from_db()
		self.user.refresh_from_db()
		self.assertEqual(payment.status, "successful")
		self.assertEqual(
			self.user.paid_until,
			_add_months(_trial_end_date(self.user.created_at), 1),
		)
		send_mail.assert_called_once()

	def test_pending_payment_return_tells_user_to_confirm_on_phone(self):
		payment = SubscriptionPayment.objects.create(
			user=self.user,
			tx_ref="pending-payment-reference",
			plan="monthly",
			network="AIRTEL",
			phone_number="256772123456",
			amount=30000,
		)

		response = self.client.get(
			reverse("subscription_return"),
			{"tx_ref": payment.tx_ref},
			follow=True,
		)

		self.assertContains(response, "awaiting Mobile Money approval")
		self.assertContains(response, "enter your PIN on your phone")
		self.assertContains(response, "will never ask for your PIN")

	@override_settings(FLW_SECRET_HASH="test-webhook-hash")
	def test_webhook_rejects_bad_signature_and_verifies_valid_payment(self):
		payment = SubscriptionPayment.objects.create(
			user=self.user,
			tx_ref="webhook-reference",
			plan="monthly",
			network="AIRTEL",
			phone_number="256772123456",
			amount=30000,
		)
		payload = {
			"event": "charge.completed",
			"data": {"tx_ref": payment.tx_ref, "id": 54321, "status": "successful"},
		}
		url = reverse("flutterwave_webhook")
		self.assertEqual(
			self.client.post(url, data=payload, content_type="application/json").status_code,
			401,
		)
		with patch("DietApp.views._verify_and_apply_payment", return_value=True) as verify:
			response = self.client.post(
				url,
				data=payload,
				content_type="application/json",
				HTTP_VERIF_HASH="test-webhook-hash",
			)

		self.assertEqual(response.status_code, 200)
		verify.assert_called_once_with(payment.tx_ref, 54321)

	def test_admin_payment_inbox_shows_new_payment_and_marks_it_reviewed(self):
		payment = SubscriptionPayment.objects.create(
			user=self.user,
			tx_ref="admin-inbox-reference",
			plan="six_months",
			network="AIRTEL",
			phone_number="256772123456",
			amount=150000,
			status="successful",
			paid_at=timezone.now(),
		)
		admin_user = get_user_model().objects.create_superuser(
			username="billing-admin",
			email="billing-admin@example.com",
			password="admin-password",
		)
		self.client.force_login(admin_user)

		response = self.client.get(reverse("admin_payments"))

		self.assertContains(response, "new successful payment")
		self.assertContains(response, "admin-inbox-reference")
		self.assertContains(response, "Airtel Money")
		payment.refresh_from_db()
		self.assertIsNotNone(payment.admin_viewed_at)

	@override_settings(FLW_SECRET_KEY="test-secret", FLW_SECRET_HASH="test-hash")
	def test_expired_member_is_sent_to_subscription_page(self):
		self.user.created_at = timezone.localdate() - timedelta(days=60)
		self.user.save(update_fields=["created_at"])

		response = self.client.get(reverse("dashboard"))

		self.assertRedirects(response, reverse("subscription"))

class ModelFormPageTests(TestCase):
	def setUp(self):
		self.user = Users.objects.create(
			user_id=1,
			full_name="Form User",
			email="forms@example.com",
			password_hash="unused",
			phone="555-0199",
			created_at=date.today(),
			last_login=date.today(),
		)
		session = self.client.session
		session["user_id"] = self.user.pk
		session.save()

	def test_generic_forms_cover_supported_user_managed_models(self):
		from django.apps import apps
		existing_models = set(apps.get_app_config("DietApp").get_models())
		registered_models = {form_class._meta.model for _, form_class in MODEL_FORM_REGISTRY.values()}
		self.assertTrue(registered_models.issubset(existing_models))
		self.assertSetEqual(
			existing_models - registered_models,
			{SupportFeedback, SupportQuestion, SubscriptionPayment},
		)

	def test_form_index_and_all_user_form_pages_render(self):
		index = self.client.get(reverse("model_forms"))
		self.assertEqual(index.status_code, 200)
		self.assertContains(index, "Nutrition forms")
		self.assertEqual(len(index.context["forms"]), 14)
		for slug in (
			"users",
			"user-profiles",
			"weight-logs",
			"foods",
			"food-logs",
			"water-logs",
			"recipes",
			"recipe-ingredients",
			"meal-plans",
			"reminders",
			"user-settings",
			"favorite-recipes",
		):
			with self.subTest(slug=slug):
				response = self.client.get(reverse("model_form", args=[slug]))
				self.assertEqual(response.status_code, 200)

		for slug, admin_model in (("achievements", "achievement"), ("user-achievements", "userachievement")):
			with self.subTest(admin_model=admin_model):
				response = self.client.get(reverse("model_form", args=[slug]))
				self.assertEqual(response.status_code, 302)
				self.assertIn(f"/admin/DietApp/{admin_model}/add/", response.url)
		for slug, admin_model in (("achievements", "achievement"), ("user-achievements", "userachievement")):
			with self.subTest(admin_model=admin_model):
				response = self.client.get(reverse("model_form", args=[slug]))
				self.assertEqual(response.status_code, 302)
				self.assertIn(f"/admin/DietApp/{admin_model}/add/", response.url)

	def test_weight_log_form_assigns_id_and_current_user(self):
		response = self.client.post(
			reverse("model_form", args=["weight-logs"]),
			{
				"user_id": self.user.pk,
				"weight_kg": "72.50",
				"log_date": "2026-09-30",
				"notes": "Morning measurement",
			},
		)

		self.assertRedirects(response, reverse("profile"))
		log = WeightLog.objects.get()
		self.assertEqual(log.weight_log_id, 1)
		self.assertEqual(log.user_id, self.user)

	def test_weight_log_previous_page_returns_to_food_log_then_dashboard(self):
		weight_log_form = self.client.get(reverse("model_form", args=["weight-logs"]))
		self.assertEqual(weight_log_form.context["previous_page_url"], reverse("food_log"))

		food_log = self.client.get(reverse("food_log"))
		self.assertEqual(food_log.context["previous_page_url"], reverse("dashboard"))

	def test_discovery_details_and_meal_plan_pages_use_existing_records(self):
		food = Food.objects.create(
			food_id=1,
			name="Trail Mix",
			brand="Field Kitchen",
			serving_size=30,
			serving_unit="g",
			calories=140,
			protein=5,
			carbs=12,
			fat=8,
			user_id=self.user,
			barcode="0123456789",
		)
		other_user = Users.objects.create(
			user_id=2,
			full_name="Other User",
			email="other@example.com",
			password_hash="unused",
			phone="555-0198",
			created_at=date.today(),
			last_login=date.today(),
		)
		Food.objects.create(
			food_id=2,
			name="Trail Mix",
			serving_size=30,
			serving_unit="g",
			calories=140,
			protein=5,
			carbs=12,
			fat=8,
			user_id=other_user,
			barcode="9876543210",
		)
		recipe = Recipe.objects.create(
			recipe_id=1,
			name="Berry Oats",
			description="A simple breakfast",
			prep_time_minutes=5,
			cook_time_minutes=0,
			total_time_minutes=5,
			servings=1,
			calories_per_serving=280,
			protein_per_serving=12,
			carbs_per_serving=44,
			fat_per_serving=6,
			instructions=["Mix and serve"],
			is_public=True,
		)

		search = self.client.get(reverse("food_search"), {"q": "0123456789"})
		self.assertContains(search, "Trail Mix")
		self.assertNotContains(search, "9876543210")
		self.assertContains(self.client.get(reverse("food_detail", args=[food.pk])), "140 kcal")
		self.assertEqual(self.client.get(reverse("food_detail", args=[2])).status_code, 404)
		self.assertContains(self.client.get(reverse("recipe_detail", args=[recipe.pk])), "Mix and serve")
		self.assertEqual(self.client.get(reverse("meal_plan")).status_code, 200)

		food_log_form = self.client.get(
			reverse("model_form", args=["food-logs"]), {"food_id": food.pk}
		)
		meal_plan_form = self.client.get(
			reverse("model_form", args=["meal-plans"]), {"recipe_id": recipe.pk}
		)
		self.assertEqual(food_log_form.context["form"].initial["food_id"], food)
		self.assertEqual(meal_plan_form.context["form"].initial["recipe_id"], recipe)

	def test_onboarding_and_progress_pages_render_tracker_state(self):
		today = timezone.localdate()
		onboarding = self.client.get(reverse("getting_started"))
		self.assertContains(onboarding, "Set up profile")
		self.assertContains(onboarding, "Set goals")
		progress = self.client.get(reverse("progress"))
		self.assertEqual(progress.status_code, 200)
		self.assertEqual(len(progress.context["daily_history"]), 7)
		self.assertEqual(progress.context["daily_history"][-1]["date"], today)
		self.assertContains(progress, "Calorie intake")
		self.assertContains(progress, "chart-track")

	def test_achievements_render_badges_and_activity_streak(self):
		achievement = Achievement.objects.create(
			achievement_id=1,
			name="Three Day Streak",
			description="Log activity for three days.",
			icon_name="ic_streak",
			criteria_type="streak",
			criteria_value=3,
			badge_image="ic_streak",
		)
		UserAchievement.objects.create(
			user_achievement_id=1,
			user_id=self.user,
			achievement_id=achievement,
			progress=3,
			is_completed=True,
		)

		response = self.client.get(reverse("achievements"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Three Day Streak")
		self.assertContains(response, "🔥")
		self.assertContains(response, "Earned")
		self.assertEqual(response.context["badges"][0]["percentage"], 100)
		self.assertEqual(response.context["streak"]["current"], 0)

	def test_dashboard_and_module_pages_require_login(self):
		self.client.post("/logout/")
		for url_name in ("dashboard", "account_details", "account_edit", "profile", "diet", "goals", "achievements", "settings"):
			with self.subTest(url_name=url_name):
				response = self.client.get(reverse(url_name))
				self.assertRedirects(response, reverse("login"))

	def test_account_edit_updates_only_the_signed_in_users_details(self):
		response = self.client.post(
			reverse("account_edit"),
			{"full_name": "Updated Name", "email": self.user.email, "phone": self.user.phone},
		)
		self.assertRedirects(response, reverse("account_details"))
		self.user.refresh_from_db()
		self.assertEqual(self.user.full_name, "Updated Name")
		self.assertContains(self.client.get(reverse("account_details")), "Updated Name")

	def test_profile_form_saves_only_for_the_signed_in_user(self):
		response = self.client.post(
			reverse("profile_add"),
			{"age": "28", "gender": "M", "weight_kg": "73.25", "height_cm": "178.00", "activity_level": "active"},
		)
		self.assertRedirects(response, reverse("profile"))
		from DietApp.models import UserProfile
		profile = UserProfile.objects.get(user_id=self.user)
		self.assertEqual(profile.weight_kg, 73.25)
		self.assertEqual(profile.age, 28)
		self.assertContains(self.client.get(reverse("profile")), "73.25")

		other_user = Users.objects.create(
			user_id=2,
			full_name="Other User",
			email="other@example.com",
			password_hash="unused",
			phone="555-0198",
			created_at=date.today(),
			last_login=date.today(),
		)
		UserProfile.objects.create(user_id=other_user, age=41, updated_at=date.today())
		self.assertNotContains(self.client.get(reverse("profile")), "41")

	def test_diet_record_edit_is_limited_to_the_current_user(self):
		Food.objects.create(
			food_id=1,
			name="My Food",
			serving_size=100,
			serving_unit="g",
			calories=120,
			protein=5,
			carbs=20,
			fat=2,
			user_id=self.user,
		)
		other_user = Users.objects.create(
			user_id=2,
			full_name="Other User",
			email="other@example.com",
			password_hash="unused",
			phone="555-0198",
			created_at=date.today(),
			last_login=date.today(),
		)
		Food.objects.create(
			food_id=2,
			name="Private Food",
			serving_size=100,
			serving_unit="g",
			calories=120,
			protein=5,
			carbs=20,
			fat=2,
			user_id=other_user,
		)

		self.assertEqual(self.client.get(reverse("model_record_edit", args=["foods", 1])).status_code, 200)
		self.assertEqual(self.client.get(reverse("model_record_edit", args=["foods", 2])).status_code, 404)

	def test_food_delete_removes_only_the_signed_in_users_selected_food(self):
		own_food = Food.objects.create(
			food_id=1,
			name="Banana",
			brand="k",
			serving_size=1,
			serving_unit="4",
			calories=1,
			protein=1,
			carbs=1,
			fat=1,
			barcode="h",
			user_id=self.user,
		)
		other_user = Users.objects.create(
			user_id=2,
			full_name="Other User",
			email="other@example.com",
			password_hash="unused",
			phone="555-0198",
			created_at=date.today(),
			last_login=date.today(),
		)
		other_food = Food.objects.create(
			food_id=2,
			name="Banana",
			serving_size=1,
			serving_unit="piece",
			calories=90,
			protein=1,
			carbs=23,
			fat=0,
			user_id=other_user,
		)

		response = self.client.post(reverse("food_delete", args=[own_food.pk]))

		self.assertRedirects(response, reverse("food_log"))
		self.assertFalse(Food.objects.filter(pk=own_food.pk).exists())
		self.assertTrue(Food.objects.filter(pk=other_food.pk).exists())


class SupportAssistantTests(TestCase):
	def setUp(self):
		self.user = Users.objects.create(
			user_id=1,
			full_name="Support User",
			email="support@example.com",
			password_hash="unused",
			phone="555-0144",
			created_at=date.today(),
			last_login=date.today(),
		)
		session = self.client.session
		session["user_id"] = self.user.pk
		session.save()

	def test_public_help_hub_and_protected_diet_ai(self):
		session = self.client.session
		session.pop("user_id", None)
		session.save()
		response = self.client.get(reverse("support"))
		self.assertEqual(response.status_code, 200)
		self.assertRedirects(self.client.get(reverse("diet_ai")), reverse("login"))
		home = self.client.get(reverse("home"))
		self.assertContains(home, "Help &amp; Support")
		self.assertContains(home, reverse("support"))
		self.assertContains(home, reverse("diet_ai"))

	def test_help_hub_has_separate_diet_ai_entry(self):
		response = self.client.get(reverse("support"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Help &amp; Support")
		self.assertContains(response, "Ask Diet AI")
		self.assertContains(response, reverse("diet_ai"))

	def test_question_answers_and_routes_user_to_requested_section(self):
		response = self.client.post(
			reverse("diet_ai"),
			{"question": "How do I log food?"},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Search for a food or recipe")
		self.assertContains(response, reverse("food_search"))
		self.assertContains(response, "Did you get the help you needed?")
		self.assertEqual(response.context["support_result"]["topic"], "food_logging")

	def test_configured_diet_ai_answer_keeps_safe_app_navigation(self):
		with patch("DietApp.views.generate_diet_ai_answer", return_value="Use Explore, then select Log."):
			response = self.client.post(
				reverse("diet_ai"),
				{"question": "How do I log food?"},
			)

		self.assertContains(response, "Use Explore, then select Log.")
		self.assertContains(response, reverse("food_search"))
		self.assertContains(response, "Diet AI")

	def test_logout_question_returns_post_logout_action(self):
		response = self.client.post(
			reverse("diet_ai"),
			{"question": "How do I log out?"},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "To securely log out")
		self.assertContains(response, f'action="{reverse("logout")}"')
		self.assertContains(response, 'type="submit">Log out</button>')

	def test_sign_in_question_links_to_sign_in_and_registration(self):
		response = self.client.post(
			reverse("diet_ai"),
			{"question": "How do I sign in?"},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, reverse("login"))
		self.assertContains(response, reverse("register"))
		self.assertContains(response, "enter your email and password")

	def test_feedback_is_saved_for_current_user(self):
		response = self.client.post(
			reverse("diet_ai"),
			{
				"action": "feedback",
				"question": "How do I log food?",
				"topic": "food_logging",
				"helpful": "false",
				"comment": "I could not find the button.",
			},
		)

		self.assertRedirects(response, reverse("diet_ai"))
		feedback = SupportFeedback.objects.get()
		self.assertEqual(feedback.user, self.user)
		self.assertEqual(feedback.topic, "food_logging")
		self.assertFalse(feedback.helpful)
		self.assertEqual(feedback.comment, "I could not find the button.")

	def test_unknown_question_returns_safe_fallback_and_navigation(self):
		response = self.client.post(
			reverse("diet_ai"),
			{"question": "Can you answer something unrelated?"},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Question sent to support")
		self.assertContains(response, "submitted your question to our support team")
		self.assertEqual(SupportQuestion.objects.count(), 1)

	def test_admin_answer_is_reused_for_normalized_repeat_question(self):
		self.client.post(
			reverse("diet_ai"),
			{"question": "Can you answer something unrelated?"},
		)
		queued_question = SupportQuestion.objects.get()
		queued_question.answer = "The administrator's verified answer."
		queued_question.save()

		response = self.client.post(
			reverse("diet_ai"),
			{"question": " CAN YOU ANSWER SOMETHING UNRELATED? "},
		)

		self.assertContains(response, "The administrator&#x27;s verified answer.")
		self.assertContains(response, "Administrator support")
		self.assertEqual(SupportQuestion.objects.count(), 1)

	def test_admin_can_answer_queue_item_and_all_askers_are_identified(self):
		self.client.post(
			reverse("diet_ai"),
			{"question": "Can you answer something unrelated?"},
		)
		first_submission = SupportQuestion.objects.get()
		other_user = Users.objects.create(
			user_id=2,
			full_name="Second Support User",
			email="second-support@example.com",
			password_hash="unused",
			phone="555-0145",
			created_at=date.today(),
			last_login=date.today(),
		)
		second_submission = SupportQuestion.objects.create(
			user=other_user,
			question=first_submission.question,
			question_key=first_submission.question_key,
		)
		admin_user = get_user_model().objects.create_superuser(
			username="diet-admin",
			email="admin@example.com",
			password="admin-secret",
		)
		self.client.force_login(admin_user)

		queue_response = self.client.get(reverse("admin:DietApp_supportquestion_changelist"))
		self.assertContains(queue_response, "Support User (support@example.com)")
		self.assertContains(queue_response, "Second Support User (second-support@example.com)")
		answer_response = self.client.post(
			reverse(
				"admin:DietApp_supportquestion_change",
				args=(first_submission.pk,),
			),
			{"topic": "general", "answer": "Use the food label or search by name.", "_save": "Save"},
		)

		self.assertEqual(answer_response.status_code, 302)
		first_submission.refresh_from_db()
		second_submission.refresh_from_db()
		self.assertEqual(first_submission.answer, "Use the food label or search by name.")
		self.assertEqual(second_submission.answer, first_submission.answer)
		self.assertContains(
			self.client.get(reverse("admin:DietApp_supportquestion_changelist")),
			"Answered",
		)

	def test_answered_support_question_notifies_user_on_dashboard(self):
		support_question = SupportQuestion.objects.create(
			user=self.user,
			question="How can I identify an unknown food?",
			question_key="test-key",
			answer="Check the ingredient and nutrition labels.",
		)

		response = self.client.get(reverse("dashboard"))

		self.assertContains(response, "Support answered your question")
		self.assertContains(response, support_question.question)
		self.assertContains(response, "Check the ingredient and nutrition labels.")
		support_question.refresh_from_db()
		self.assertIsNotNone(support_question.answer_viewed_at)
		self.assertNotContains(self.client.get(reverse("dashboard")), "Support answered your question")

	def test_diet_benefits_question_gets_an_immediate_answer(self):
		response = self.client.post(
			reverse("diet_ai"),
			{"question": "What are the benefits of a healthy diet?"},
		)

		self.assertContains(response, "provides energy and essential nutrients")
		self.assertEqual(SupportQuestion.objects.count(), 0)


class DietAIProviderTests(TestCase):
	@override_settings(DIET_AI_API_KEY="test-key", DIET_AI_MODEL="test-model")
	def test_provider_returns_model_answer(self):
		with patch("DietApp.ai_support.urlopen") as mocked_urlopen:
			mocked_urlopen.return_value.__enter__.return_value.read.return_value = (
				b'{"choices":[{"message":{"content":"Here is the app guidance."}}]}'
			)
			answer = generate_diet_ai_answer(
				"How do I log food?", "food_logging", "Use Explore to search."
			)

		self.assertEqual(answer, "Here is the app guidance.")
		self.assertEqual(mocked_urlopen.call_args.kwargs["timeout"], 12)

	@override_settings(DIET_AI_API_KEY="")
	def test_provider_skips_network_without_api_key(self):
		with patch("DietApp.ai_support.urlopen") as mocked_urlopen:
			answer = generate_diet_ai_answer("Question", "general", "Fallback")

		self.assertIsNone(answer)
		mocked_urlopen.assert_not_called()

	@override_settings(DIET_AI_API_KEY="test-key")
	def test_provider_failure_uses_local_fallback(self):
		with patch("DietApp.ai_support.urlopen", side_effect=TimeoutError):
			answer = generate_diet_ai_answer("Question", "general", "Fallback")

		self.assertIsNone(answer)
