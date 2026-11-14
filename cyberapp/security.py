"""Server-side authorization helpers."""
from functools import wraps

from flask import abort
from flask_login import current_user, login_required


def role_required(*roles):
    """Allow the view only to authenticated users whose role is in `roles` (403 otherwise)."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not current_user.has_role(*roles):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator
