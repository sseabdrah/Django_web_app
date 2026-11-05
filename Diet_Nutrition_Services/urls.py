from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path

from DietApp import views

admin.site.site_header = "Diet Administration"
admin.site.site_title = "Diet Administration"
admin.site.index_title = "Diet Services"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.Home, name="home"),
    path("login/", views.Login, name="login"),
    path("password-reset/", views.PasswordResetRequest, name="password_reset_request"),
    path("password-reset/<str:token>/", views.PasswordResetConfirm, name="password_reset_confirm"),
    path("logout/", views.Logout, name="logout"),
    path("dashboard/", views.Dashboard, name="dashboard"),
    path("onboarding/", views.Onboarding, name="onboarding"),
    path("subscription/", views.Subscription, name="subscription"),
    path("subscription/return/", views.SubscriptionReturn, name="subscription_return"),
    path("payments/flutterwave/webhook/", views.FlutterwaveWebhook, name="flutterwave_webhook"),
    path("admin-dashboard/", views.AdminDashboard, name="admin_dashboard"),
    path("admin-dashboard/users/", views.AdminUsers, name="admin_users"),
    path("admin-dashboard/users/add/", views.AdminUserFormPage, name="admin_user_add"),
    path("admin-dashboard/users/<int:record_id>/", views.AdminUserDetail, name="admin_user_detail"),
    path("admin-dashboard/users/<int:record_id>/reset-password/", views.AdminUserPasswordReset, name="admin_user_password_reset"),
    path("admin-dashboard/users/<int:record_id>/edit/", views.AdminUserFormPage, name="admin_user_edit"),
    path("admin-dashboard/users/<int:record_id>/delete/", views.AdminUserDelete, name="admin_user_delete"),
    path("admin-dashboard/payments/", views.AdminPayments, name="admin_payments"),
    path("admin-dashboard/manage/<slug:catalog_slug>/", views.AdminCatalog, name="admin_catalog"),
    path("admin-dashboard/manage/<slug:catalog_slug>/add/", views.AdminCatalogForm, name="admin_catalog_add"),
    path("admin-dashboard/manage/<slug:catalog_slug>/<int:record_id>/edit/", views.AdminCatalogForm, name="admin_catalog_edit"),
    path("admin-dashboard/manage/<slug:catalog_slug>/<int:record_id>/delete/", views.AdminCatalogDelete, name="admin_catalog_delete"),
    path("admin-dashboard/support/", views.AdminSupport, name="admin_support"),
    path("admin-dashboard/support/<int:record_id>/", views.AdminSupportAnswer, name="admin_support_answer"),
    path("admin-dashboard/reports/", views.AdminReports, name="admin_reports"),
    path("getting-started/", views.GettingStarted, name="getting_started"),
    path("support/", views.Support, name="support"),
    path("diet-ai/", views.DietAI, name="diet_ai"),
    path("progress/", views.Progress, name="progress"),
    path("explore/", views.FoodSearch, name="food_search"),
    path("foods/<int:record_id>/", views.FoodDetail, name="food_detail"),
    path("foods/<int:record_id>/log/", views.LogFoodPortion, name="log_food_portion"),
    path("water/", views.WaterTracker, name="water_tracker"),
    path("water/<int:record_id>/delete/", views.DeleteWaterLog, name="water_log_delete"),
    path("recipes/<int:record_id>/", views.RecipeDetail, name="recipe_detail"),
    path("recipes/<int:record_id>/log/", views.LogRecipe, name="log_recipe"),
    path("recipes/<int:record_id>/review/", views.SaveRecipeReview, name="save_recipe_review"),
    path("recipes/<int:record_id>/ingredients/add/", views.AddIngredientsToShoppingList, name="add_ingredients"),
    path("shopping-list/", views.ShoppingList, name="shopping_list"),
    path("shopping-list/<int:record_id>/", views.UpdateShoppingItem, name="update_shopping_item"),
    path("meal-plan/", views.MealPlanPage, name="meal_plan"),
    path("meal-plan/generate/", views.GenerateMealPlan, name="generate_meal_plan"),
    path("goals/recalculate/", views.RecalculateTargets, name="recalculate_targets"),
    path("recipes/<int:record_id>/favorite/", views.ToggleRecipeFavorite, name="toggle_recipe_favorite"),
    path("export/", views.ExportNutritionData, name="export_nutrition_data"),
    path("account/", views.AccountDetails, name="account_details"),
    path("account/edit/", views.AccountDetailsFormPage, name="account_edit"),
    path("profile/", views.Profile, name="profile"),
    path("profile/add/", views.ProfileFormPage, name="profile_add"),
    path("profile/edit/", views.ProfileFormPage, name="profile_edit"),
    path("diet/", views.DietInformation, name="diet"),
    path("food-log/", views.DietInformation, name="food_log"),
    path("goals/", views.Goals, name="goals"),
    path("goals/edit/", views.GoalsFormPage, name="goals_edit"),
    path("achievements/", views.Achievements, name="achievements"),
    path("settings/", views.Settings, name="settings"),
    path("settings/edit/", views.SettingsFormPage, name="settings_edit"),
    path("forms/", views.ModelForms, name="model_forms"),
    path("forms/<slug:model_slug>/", views.ModelFormPage, name="model_form"),
    path("forms/<slug:model_slug>/<int:record_id>/edit/", views.ModelRecordEditPage, name="model_record_edit"),
    path("foods/<int:record_id>/delete/", views.DeleteFood, name="food_delete"),
    path("register/", views.Register, name="register"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
