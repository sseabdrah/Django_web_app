from django.urls import reverse


def navigation_context(request):
	model_slug = getattr(request.resolver_match, "kwargs", {}).get("model_slug")
	previous_page_url = reverse("food_log") if model_slug == "weight-logs" else reverse("dashboard")
	return {"previous_page_url": previous_page_url}