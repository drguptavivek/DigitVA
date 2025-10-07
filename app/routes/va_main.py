import sqlalchemy as sa
from app import db
from app.forms import VaMyprofileForm, VaForcePasswordChangeForm
from app.utils import va_render_serialisedates
from app.decorators import va_validate_permissions
from flask_login import login_required, current_user
from app.utils.va_permission.va_permission_01_abortwithflash import (
    va_permission_abortwithflash,
)
from app.models import (
    VaSubmissions,
    VaReviewerReview,
    VaStatuses,
    VaAllocations,
    VaAllocation,
    VaInitialAssessments,
    VaCoderReview,
    VaFinalAssessments,
)
from flask import (
    Blueprint,
    render_template,
    render_template_string,
    flash,
    jsonify,
    redirect,
    url_for
)
from collections import Counter
from datetime import datetime

va_main = Blueprint("va_main", __name__)

@va_main.route('/health', methods=['GET'])  
def health_check():  
    return jsonify({"status": "healthy"}), 200

@va_main.route("/")
@va_main.route("/index")
@va_main.route("/vaindex")
def va_index():
    return render_template("va_frontpages/va_index.html")


@va_main.route("/vadashboard/<va_role>")
@login_required
@va_validate_permissions()
def va_dashboard(va_role):
    if va_role == "coder":
        va_form_access = current_user.get_coder_va_forms()
        va_accepted_forms = db.session.scalars(
            sa.select(VaReviewerReview.va_sid).where(
                (VaReviewerReview.va_rreview_status == VaStatuses.active)
                & (VaReviewerReview.va_rreview == "accepted")
            )
        ).all()
        va_inicoded_forms = db.session.scalars(
            sa.select(VaInitialAssessments.va_sid).where(
                (VaInitialAssessments.va_iniassess_status == VaStatuses.active)
            )
        ).all()
        va_fincoded_forms = db.session.scalars(
            sa.select(VaFinalAssessments.va_sid).where(
                (VaFinalAssessments.va_finassess_status == VaStatuses.active)
            )
        ).all()
        va_error_forms = db.session.scalars(
            sa.select(VaCoderReview.va_sid).where(
                (VaCoderReview.va_creview_status == VaStatuses.active)
            )
        ).all()
        va_alreadyreserved = db.session.scalars(
            sa.select(VaAllocations.va_sid).where(
                (VaAllocations.va_allocation_status == VaStatuses.active) &
                (VaAllocations.va_allocation_for == VaAllocation.coding)
            )
        ).all()
        if va_form_access:
            va_total_forms = db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaSubmissions)
                .where(
                    sa.sql.and_(
                        VaSubmissions.va_form_id.in_(va_form_access),
                        VaSubmissions.va_narration_language.in_(
                            current_user.vacode_language
                        ),
                        VaSubmissions.va_sid.notin_(va_inicoded_forms),
                        VaSubmissions.va_sid.notin_(va_fincoded_forms),
                        VaSubmissions.va_sid.notin_(va_error_forms),
                        VaSubmissions.va_sid.notin_(va_alreadyreserved),
                    )
                )
            )
            # the following is the temporary code to allow TR01 to code only old 88 forms, please remove it later
            if current_user.is_coder(va_form = "UNSW01TR0101"):
                va_total_forms = db.session.scalar(
                    sa.select(sa.func.count())
                    .select_from(VaSubmissions)
                    .where(
                        sa.sql.and_(
                            VaSubmissions.va_form_id.in_(va_form_access),
                            VaSubmissions.va_narration_language.in_(
                                current_user.vacode_language
                            ),
                            VaSubmissions.va_sid.notin_(va_inicoded_forms),
                            VaSubmissions.va_sid.notin_(va_fincoded_forms),
                            VaSubmissions.va_sid.notin_(va_error_forms),
                            VaSubmissions.va_sid.notin_(va_alreadyreserved),
                            sa.func.date(VaSubmissions.va_submission_date) <= datetime(2025, 9, 9).date()
                        )
                    )
                )
            # till here, remove this part for TR01 in future
            va_forms_completed = db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaCoderReview)
                .where(
                    sa.sql.and_(
                        VaCoderReview.va_creview_by == current_user.user_id,
                        VaCoderReview.va_creview_status == VaStatuses.active,
                    )
                )
            ) + db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaFinalAssessments)
                .where(
                    sa.sql.and_(
                        VaFinalAssessments.va_finassess_by == current_user.user_id,
                        VaFinalAssessments.va_finassess_status == VaStatuses.active,
                    )
                )
            )
            va_forms_raw1 = (
                db.session.execute(
                    sa.select(
                        sa.func.date(VaSubmissions.va_submission_date).label(
                            "va_submission_date"
                        ),
                        VaSubmissions.va_form_id,
                        VaCoderReview.va_sid,
                        VaSubmissions.va_uniqueid_masked,
                        VaSubmissions.va_data_collector,
                        VaSubmissions.va_deceased_age,
                        VaSubmissions.va_deceased_gender,
                        VaCoderReview.va_creview_createdat.label("va_coding_date"),
                        sa.literal("Not Codeable").label("va_code_status"),
                    )
                    .outerjoin(
                        VaSubmissions,
                        sa.sql.and_(
                            VaCoderReview.va_sid == VaSubmissions.va_sid,
                        ),
                    )
                    .where(
                        sa.sql.and_(
                            VaCoderReview.va_creview_by == current_user.user_id,
                            VaCoderReview.va_creview_status == VaStatuses.active,
                        )
                    )
                )
                .mappings()
                .all()
            )
            va_forms_raw2 = (
                db.session.execute(
                    sa.select(
                        sa.func.date(VaSubmissions.va_submission_date).label(
                            "va_submission_date"
                        ),
                        VaSubmissions.va_form_id,
                        VaFinalAssessments.va_sid,
                        VaSubmissions.va_uniqueid_masked,
                        VaSubmissions.va_data_collector,
                        VaSubmissions.va_deceased_age,
                        VaSubmissions.va_deceased_gender,
                        VaFinalAssessments.va_finassess_createdat.label(
                            "va_coding_date"
                        ),
                        sa.literal("VA Coding Completed").label("va_code_status"),
                    )
                    .outerjoin(
                        VaSubmissions,
                        sa.sql.and_(
                            VaFinalAssessments.va_sid == VaSubmissions.va_sid,
                        ),
                    )
                    .where(
                        sa.sql.and_(
                            VaFinalAssessments.va_finassess_by == current_user.user_id,
                            VaFinalAssessments.va_finassess_status == VaStatuses.active,
                        )
                    )
                )
                .mappings()
                .all()
            )
            va_forms_raw = va_forms_raw1 + va_forms_raw2
            va_date_fields = ["va_submission_date", "va_coding_date"]
            va_forms = [
                va_render_serialisedates(row, va_date_fields) for row in va_forms_raw
            ]
        else:
            va_total_forms = 0
            va_forms_completed = 0
            va_forms = []
        va_has_allocation = db.session.scalar(
            sa.select(VaAllocations.va_sid).where(
                (VaAllocations.va_allocated_to == current_user.user_id)
                & (VaAllocations.va_allocation_for == VaAllocation.coding)
                & (VaAllocations.va_allocation_status == VaStatuses.active)
            )
        )
        recent_final = db.session.scalars(
            sa.select(VaFinalAssessments.va_sid).where(
                (VaFinalAssessments.va_finassess_by == current_user.user_id)
                & (VaFinalAssessments.va_finassess_status == VaStatuses.active)
                & (
                    VaFinalAssessments.va_finassess_createdat
                    + sa.text("interval '24 hours'")
                    > sa.func.now()
                )
            )
        ).all()
        recent_review = db.session.scalars(
            sa.select(VaCoderReview.va_sid).where(
                (VaCoderReview.va_creview_by == current_user.user_id)
                & (VaCoderReview.va_creview_status == VaStatuses.active)
                & (
                    VaCoderReview.va_creview_createdat + sa.text("interval '24 hours'")
                    > sa.func.now()
                )
            )
        ).all()
        user_recent_final = db.session.scalars(
            sa.select(VaFinalAssessments.va_sid).where(
                (VaFinalAssessments.va_finassess_by == current_user.user_id)
            )
        ).all()
        user_recent_review = db.session.scalars(
            sa.select(VaCoderReview.va_sid).where(
                (VaCoderReview.va_creview_by == current_user.user_id)
            )
        ).all()
        lst_va = user_recent_final + user_recent_review
        counts_va = Counter(lst_va)
        result_va = [item for item in lst_va if counts_va[item] > 1]
        return render_template(
            "va_frontpages/va_code.html",
            va_total_forms=va_total_forms,
            va_forms_completed=va_forms_completed,
            va_forms=va_forms,
            va_has_allocation=va_has_allocation,
            va_recodeable=list(set(recent_final + recent_review) - set(result_va))
        )
    elif va_role == "reviewer":
        va_form_access = current_user.get_reviewer_va_forms()
        if va_form_access:
            va_total_forms = db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaSubmissions)
                .where(
                    sa.sql.and_(
                        VaSubmissions.va_form_id.in_(va_form_access),
                        VaSubmissions.va_narration_language.in_(
                            current_user.vacode_language
                        ),
                    )
                )
            )
            va_forms_completed = db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaReviewerReview)
                .where(
                    sa.sql.and_(
                        VaReviewerReview.va_rreview_by == current_user.user_id,
                        VaReviewerReview.va_rreview_status == VaStatuses.active,
                    )
                )
            )
            va_forms_raw = (
                db.session.execute(
                    sa.select(
                        sa.func.date(VaSubmissions.va_submission_date).label(
                            "va_submission_date"
                        ),
                        VaSubmissions.va_form_id,
                        VaSubmissions.va_sid,
                        VaSubmissions.va_uniqueid_masked,
                        VaSubmissions.va_data_collector,
                        VaSubmissions.va_deceased_age,
                        VaSubmissions.va_deceased_gender,
                        sa.case(
                            (
                                VaReviewerReview.va_rreview_status == VaStatuses.active,
                                sa.literal("Reviewed"),
                            ),
                            else_=sa.literal("Not Reviewed"),
                        ).label("va_review_status"),
                        sa.func.date(VaReviewerReview.va_rreview_createdat).label(
                            "va_rreview_createdat"
                        ),
                        VaReviewerReview.va_rreview_by,
                    )
                    .outerjoin(
                        VaReviewerReview,
                        sa.sql.and_(
                            VaReviewerReview.va_sid == VaSubmissions.va_sid,
                            VaReviewerReview.va_rreview_status == VaStatuses.active,
                        ),
                    )
                    .where(
                        sa.sql.and_(
                            VaSubmissions.va_form_id.in_(va_form_access),
                            VaSubmissions.va_narration_language.in_(
                                current_user.vacode_language
                            ),
                        )
                    )
                )
                .mappings()
                .all()
            )
            va_date_fields = ["va_submission_date", "va_rreview_createdat"]
            va_forms = [
                va_render_serialisedates(row, va_date_fields) for row in va_forms_raw
            ]
        else:
            va_total_forms = 0
            va_forms_completed = 0
            va_forms = []
        va_has_allocation = db.session.scalar(
            sa.select(VaAllocations.va_sid).where(
                (VaAllocations.va_allocated_to == current_user.user_id)
                & (VaAllocations.va_allocation_for == VaAllocation.reviewing)
                & (VaAllocations.va_allocation_status == VaStatuses.active)
            )
        )
        return render_template(
            "va_frontpages/va_reviewer.html",
            va_total_forms=va_total_forms,
            va_forms_completed=va_forms_completed,
            va_forms=va_forms,
            va_has_allocation=va_has_allocation,
        )
    elif va_role == "sitepi":
        return render_template_string("<h1>success: site_pi</h1>")
    else:
        va_permission_abortwithflash("Invalid dashboard path.", 404)


@va_main.route("/vaprofile", methods=["GET", "POST"])
@login_required
def va_profile():
    form = VaMyprofileForm()
    stmt = sa.select(sa.func.distinct(VaSubmissions.va_narration_language))
    result = db.session.execute(stmt).scalars().all()
    lang_choices = sorted([lang for lang in result if lang])
    form.va_languages.choices = [(lang, lang) for lang in lang_choices]
    if form.va_update_password.data and form.validate_on_submit():
        if not form.va_current_password.data or not form.va_new_password.data:
            flash("Please fill all password fields to update.", "warning")
        elif not current_user.check_password(form.va_current_password.data):
            flash("Incorrect current password.", "danger")
        else:
            current_user.set_password(form.va_new_password.data)
            db.session.commit()
            flash("Password updated successfully.", "success")
        return render_template("va_frontpages/va_myprofile.html", form=form)
    elif form.va_update_languages.data:
        current_user.vacode_language = form.va_languages.data
        db.session.commit()
        flash("VA Languages updated successfully.", "success")
        return render_template("va_frontpages/va_myprofile.html", form=form)
    form.va_languages.data = current_user.vacode_language
    return render_template("va_frontpages/va_myprofile.html", form=form)


@va_main.route("/force-password-change", methods=["GET", "POST"])
@login_required
def force_password_change():
    if current_user.pw_reset_t_and_c:
        return redirect(url_for("va_main.va_dashboard", va_role="coder"))
    form = VaForcePasswordChangeForm()
    if form.validate_on_submit():
        current_user.set_password(form.new_password.data)
        current_user.pw_reset_t_and_c = True
        db.session.commit()
        flash("Password updated successfully.", "success")
        return redirect(url_for("va_main.va_dashboard", va_role="coder"))
    return render_template("va_form_partials/va_forcepwreset.html", form=form)