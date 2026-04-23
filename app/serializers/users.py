"""User serializers."""


def serialize_user(user):
    return {
        "user_id": str(user.user_id),
        "email": user.email,
        "name": user.name,
        "status": user.user_status.value,
        "email_verified": bool(user.email_verified),
        "phone": user.phone,
        "landing_page": user.landing_page,
        "languages": user.vacode_language or [],
        "is_admin": user.is_admin(),
    }
