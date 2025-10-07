import sqlalchemy as sa
from app import db
from app.models import VaForms, VaStatuses


def va_form_deleteform(form_id):
    session = db.session
    va_form = session.scalars(
        sa.select(VaForms).where(VaForms.form_id == form_id)
    ).first()
    if not va_form:
        print(f"Failed [Form ID {form_id} not found.]")
        return
    va_form.form_status = VaStatuses.deactive
    session.commit()
    print(f"Success [Deleted form '{form_id}'.]")
