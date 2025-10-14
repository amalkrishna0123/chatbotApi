# Create a new file middleware.py in your app
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin
from urllib.parse import urlparse

# middleware.py - Update to allow the initial insurance question
# middleware.py
class AuthenticationMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if (request.path.startswith('/api/auth/') or
            request.path.startswith('/static/')):
            return None
        if request.path == '/':
            return None

        # NEW: let the insurance-chat endpoint run until user chooses a role
        if (request.path.startswith('/api/insurance-chat/') and
            request.method == 'POST'):
            try:
                body = json.loads(request.body.decode('utf-8'))
                # allow very first call (empty) and the “Yes” answer
                if body.get("user_text", "").lower() in {"", "yes"}:
                    return None
            except Exception:
                pass

        if not request.user.is_authenticated:
            return JsonResponse(
                {"error": "Authentication required", "login_required": True},
                status=401)
        return None