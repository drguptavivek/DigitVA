import uuid
import traceback
import sqlalchemy as sa
from app import db
from app.models import VaUsers, VaStatuses


def va_user_delete(user_id):
    session = db.session
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        print(f"Failed [Invalid UUID '{user_id}' format.]")
        print(traceback.format_exc())
        return
    user = session.scalars(
        sa.select(VaUsers).where(VaUsers.user_id == user_uuid)
    ).first()
    if not user:
        print(f"Failed [User ID {user_id} not found.]")
        return
    user.user_status = VaStatuses.deactive
    session.commit()
    print(f"Success [User '{user_id}' deleted.]")
