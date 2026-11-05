from django.contrib import admin
from DietApp.models import (Users,UserProfile,WeightLog,Food,FoodLog,WaterLog,Recipe,RecipeIngredient,MealPlan,Achievement,UserAchievement,Reminder,UserSetting,FavoriteRecipe,SupportQuestion)

# Register your models here.
Users._meta.verbose_name_plural = "Users"
admin.site.register(Users)
admin.site.register(UserProfile)
admin.site.register(WeightLog)
admin.site.register(Food)
admin.site.register(FoodLog)
admin.site.register(WaterLog)
admin.site.register(Recipe)
admin.site.register(RecipeIngredient)
admin.site.register(MealPlan)
admin.site.register(Achievement)
admin.site.register(UserAchievement)
admin.site.register(Reminder)
admin.site.register(UserSetting)
admin.site.register(FavoriteRecipe)


@admin.register(SupportQuestion)
class SupportQuestionAdmin(admin.ModelAdmin):
	list_display = ("question", "user_identity", "topic", "answer_status", "created_at", "updated_at")
	list_filter = ("topic", "created_at")
	search_fields = ("question", "answer", "user__full_name", "user__email")
	readonly_fields = ("user", "user_identity", "question", "question_key", "created_at")
	fields = ("user_identity", "question", "topic", "answer", "created_at")

	@admin.display(description="Asked by")
	def user_identity(self, obj):
		if not obj.user:
			return "Deleted user"
		return f"{obj.user.full_name} ({obj.user.email})"

	@admin.display(description="Status")
	def answer_status(self, obj):
		return "Answered" if obj.answer else "Awaiting answer"

	def save_model(self, request, obj, form, change):
		super().save_model(request, obj, form, change)
		if obj.answer:
			SupportQuestion.objects.filter(question_key=obj.question_key).exclude(
				pk=obj.pk
			).update(answer=obj.answer, answer_viewed_at=None)