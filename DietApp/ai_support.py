import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings


def generate_diet_ai_answer(question, topic, fallback_answer):
    api_key = getattr(settings, "DIET_AI_API_KEY", "")
    if not api_key:
        return None

    payload = {
        "model": getattr(settings, "DIET_AI_MODEL", "gpt-4o-mini"),
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Diet AI, the in-app support assistant for Diet Services. "
                    "Answer questions only about using this app. Be concise, practical, "
                    "and friendly. Use only the verified app guidance in the user message; "
                    "do not invent features or steps. Do not provide diagnoses, "
                    "treatment plans, or personalized medical advice; direct health-related "
                    "medical questions to a qualified professional. Page navigation is "
                    "provided separately by the app, so do not output URLs. Return only "
                    "the answer text."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n"
                    f"Matched app topic: {topic}\n"
                    f"Verified app guidance: {fallback_answer}"
                ),
            },
        ],
        "temperature": 0.2,
        "max_tokens": 240,
    }
    request = Request(
        getattr(settings, "DIET_AI_API_URL", "https://api.openai.com/v1/chat/completions"),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=12) as response:
            result = json.loads(response.read().decode("utf-8"))
        answer = result["choices"][0]["message"]["content"].strip()
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError):
        return None

    return answer[:2000] if answer else None