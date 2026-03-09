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
    url_for,
    request
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
        sitepi_sites = sorted(current_user.get_site_pi_sites())
        if not sitepi_sites:
            va_permission_abortwithflash("No sites assigned for supervision.", 403)

        default_site = sitepi_sites[0] if sitepi_sites else None
        default_site_data = None

        if default_site:
            total_submissions_query = sa.text("""
                SELECT COUNT(*) as total_submissions
                FROM va_submissions
                WHERE va_form_id = :site_id
            """)

            total_coded_query = sa.text("""
                SELECT COUNT(*) as total_coded
                FROM va_final_assessments
                WHERE va_finassess_status = 'active'
                AND upper(split_part(va_sid, '-', -1)) = :site_id
            """)

            total_not_codeable_query = sa.text("""
                SELECT COUNT(*) as total_not_codeable
                FROM va_coder_review
                WHERE va_creview_status = 'active'
                AND upper(split_part(va_sid, '-', -1)) = :site_id
            """)
            
            coder_wise_kpis = sa.text("""
                SELECT 
                    u.name as "VA Coder", 
                    u.pw_reset_t_and_c as "VA Coder Followed On-Boarding Mail for DigitVA", 
                    COALESCE(work.total_done, 0) as "Total VA Forms Coded by VA Coder", 
                    COALESCE(review.total_errors, 0) as "Total VA Forms Marked as Not-Codeable by VA Coder" 
                FROM va_users u
                
                -- Join 1: Assessments Count
                LEFT JOIN (
                    SELECT va_finassess_by, count(*) as total_done
                    FROM va_final_assessments
                    WHERE va_finassess_status = 'active'
                    -- Yahan direct :site_id concatenate kar diya
                    AND va_sid ILIKE '%-' || :site_id 
                    GROUP BY va_finassess_by
                ) work ON u.user_id = work.va_finassess_by
                
                -- Join 2: Coder Review Count
                LEFT JOIN (
                    SELECT va_creview_by, count(*) as total_errors
                    FROM va_coder_review
                    WHERE va_creview_status = 'active'
                    -- Yahan bhi direct :site_id
                    AND va_sid ILIKE '%-' || :site_id 
                    GROUP BY va_creview_by
                ) review ON u.user_id = review.va_creview_by
                
                -- Main Filter
                WHERE
                    -- JSON array build karte waqt :site_id pass kiya
                    u.permission::jsonb @> jsonb_build_object('coder', jsonb_build_array(:site_id))
                ORDER BY "VA Coder";
            """)

            submissions_result = db.session.execute(total_submissions_query, {"site_id": default_site}).fetchone()
            coded_result = db.session.execute(total_coded_query, {"site_id": default_site}).fetchone()
            not_codeable_result = db.session.execute(total_not_codeable_query, {"site_id": default_site}).fetchone()
            coder_kpis = db.session.execute(coder_wise_kpis, {"site_id": default_site}).fetchall()

            # Get coder review records for this site (for the table)
            # review_records = db.session.scalars(
            #     sa.select(VaCoderReview).where(
            #         sa.and_(
            #             VaCoderReview.va_creview_status == VaStatuses.active,
            #             sa.func.upper(sa.func.split_part(VaCoderReview.va_sid, '-', -1)) == default_site
            #         )
            #     ).order_by(VaCoderReview.va_creview_createdat.desc())
            # ).all()

            default_site_data = {
                'total_submissions': submissions_result.total_submissions if submissions_result else 0,
                'total_coded': coded_result.total_coded if coded_result else 0,
                'total_not_codeable': not_codeable_result.total_not_codeable if not_codeable_result else 0,
                'coder_kpis': coder_kpis
                # 'review_records': review_records
            }

        return render_template(
            "va_frontpages/va_sitepi.html",
            sitepi_sites=sitepi_sites,
            default_site_data=default_site_data
        )
    else:
        va_permission_abortwithflash("Invalid dashboard path.", 404)


@va_main.route("/vadashboard/sitepi/data", methods=['GET'])
@login_required
def va_sitepi_data():
    print(f"HTMX endpoint called with args: {request.args}")
    site_id = request.args.get('siteSelect')
    print(f"Site ID received: {site_id}")
    if not site_id:
        return "<div class='text-center py-5'><p class='text-muted'>No site selected.</p></div>"

    sitepi_sites = sorted(current_user.get_site_pi_sites())
    if site_id not in sitepi_sites:
        return "<div class='text-center py-5'><p class='text-danger'>Access denied for this site.</p></div>"

    total_submissions_query = sa.text("""
        SELECT COUNT(*) as total_submissions
        FROM va_submissions
        WHERE va_form_id = :site_id
    """)

    total_coded_query = sa.text("""
        SELECT COUNT(*) as total_coded
        FROM va_final_assessments
        WHERE va_finassess_status = 'active'
        AND upper(split_part(va_sid, '-', -1)) = :site_id
    """)

    total_not_codeable_query = sa.text("""
        SELECT COUNT(*) as total_not_codeable
        FROM va_coder_review
        WHERE va_creview_status = 'active'
        AND upper(split_part(va_sid, '-', -1)) = :site_id
    """)
    
    coder_wise_kpis = sa.text("""
        SELECT 
            u.name as "VA Coder", 
            u.pw_reset_t_and_c as "VA Coder Followed On-Boarding Mail for DigitVA", 
            COALESCE(work.total_done, 0) as "Total VA Forms Coded by VA Coder", 
            COALESCE(review.total_errors, 0) as "Total VA Forms Marked as Not-Codeable by VA Coder" 
        FROM va_users u
        
        -- Join 1: Assessments Count
        LEFT JOIN (
            SELECT va_finassess_by, count(*) as total_done
            FROM va_final_assessments
            WHERE va_finassess_status = 'active'
            -- Yahan direct :site_id concatenate kar diya
            AND va_sid ILIKE '%-' || :site_id 
            GROUP BY va_finassess_by
        ) work ON u.user_id = work.va_finassess_by
        
        -- Join 2: Coder Review Count
        LEFT JOIN (
            SELECT va_creview_by, count(*) as total_errors
            FROM va_coder_review
            WHERE va_creview_status = 'active'
            -- Yahan bhi direct :site_id
            AND va_sid ILIKE '%-' || :site_id 
            GROUP BY va_creview_by
        ) review ON u.user_id = review.va_creview_by
        
        -- Main Filter
        WHERE
            -- JSON array build karte waqt :site_id pass kiya
            u.permission::jsonb @> jsonb_build_object('coder', jsonb_build_array(:site_id))
        ORDER BY "VA Coder";
    """)

    submissions_result = db.session.execute(total_submissions_query, {"site_id": site_id}).fetchone()
    coded_result = db.session.execute(total_coded_query, {"site_id": site_id}).fetchone()
    not_codeable_result = db.session.execute(total_not_codeable_query, {"site_id": site_id}).fetchone()
    coder_kpis = db.session.execute(coder_wise_kpis, {"site_id": site_id}).fetchall()

    # Get coder review records for this site (for the table)
    # review_records = db.session.scalars(
    #     sa.select(VaCoderReview).where(
    #         sa.and_(
    #             VaCoderReview.va_creview_status == VaStatuses.active,
    #             sa.func.upper(sa.func.split_part(VaCoderReview.va_sid, '-', -1)) == site_id
    #         )
    #     ).order_by(VaCoderReview.va_creview_createdat.desc())
    # ).all()

    site_data = {
        'total_submissions': submissions_result.total_submissions if submissions_result else 0,
        'total_coded': coded_result.total_coded if coded_result else 0,
        'total_not_codeable': not_codeable_result.total_not_codeable if not_codeable_result else 0,
        'coder_kpis': coder_kpis,
        #'review_records': review_records,
        'site_id': site_id
    }

    return render_template_string("""
    <h3 class="text-primary mb-3 mt-4" style="font-size: 24px; font-weight: 600;">
        <i class="fas fa-hospital me-2"></i> Site & VA Form: AIIMS, ND (ICMR - Telephonic WHO VA 2022)
        </h3>
        <!-- KPI cards -->
        <div class="row mb-4 g-3">
        <div class="col-md-4">
            <div class="card shadow-sm border-0 rounded-3 h-100">
            <div class="card-body p-4">
                <div class="d-flex flex-column align-items-center">
                <div class="mb-3">
                    <i class="fas fa-file-alt text-primary fa-2x"></i>
                </div>
                <h5 class="text-primary fw-semibold mb-3">Total VA Submissions ({{ sitepi_sites[0] if sitepi_sites else 'N/A' }})</h5>
                <div class="d-flex align-items-baseline">
                    <h2 class="display-4 fw-bold text-primary mb-0">{{ default_site_data.total_submissions if default_site_data else 0 }}</h2>
                    <span class="ms-2 text-secondary small">submissions</span>
                </div>
                </div>
            </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card shadow-sm border-0 rounded-3 h-100">
            <div class="card-body p-4">
                <div class="d-flex flex-column align-items-center">
                <div class="mb-3">
                    <i class="fas fa-check-circle text-success fa-2x"></i>
                </div>
                <h5 class="text-success fw-semibold mb-3">Total VA Submissions Coded ({{ sitepi_sites[0] if sitepi_sites else 'N/A' }})</h5>
                <div class="d-flex align-items-baseline">
                    <h2 class="display-4 fw-bold text-success mb-0">{{ default_site_data.total_coded if default_site_data else 0 }}</h2>
                    <span class="ms-2 text-secondary small">submissions</span>
                </div>
                </div>
            </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card shadow-sm border-0 rounded-3 h-100">
            <div class="card-body p-4">
                <div class="d-flex flex-column align-items-center">
                <div class="mb-3">
                    <i class="fas fa-times-circle text-danger fa-2x"></i>
                </div>
                <h5 class="text-danger fw-semibold mb-3">Total VA Submissions Not Codeable ({{ sitepi_sites[0] if sitepi_sites else 'N/A' }})</h5>
                <div class="d-flex align-items-baseline">
                    <h2 class="display-4 fw-bold text-danger mb-0">{{ default_site_data.total_not_codeable if default_site_data else 0 }}</h2>
                    <span class="ms-2 text-secondary small">submissions</span>
                </div>
                </div>
            </div>
            </div>
        </div>
        </div>
        <!--
        <h3 class="text-primary mb-3" style="font-size: 28px; font-weight: 600;">
            VA Forms Marked as Not Codeable ({{ sitepi_sites[0] if sitepi_sites else 'N/A' }})
        </h3>
        -->

        <!-- Table -->
        <!--
        <div class="table-responsive">
        <table id="sitepiTable" class="table table-hover align-middle table-striped nowrap" style="min-width: 800px;">
            <thead>
            <tr>
                <th>VA SID</th>
                <th>Review Reason</th>
                <th>Review Date</th>
                <th>Action</th>
            </tr>
            </thead>
            <tbody>
            {% for record in default_site_data.review_records %}
            <tr>
                <td>{{ record.va_sid }}</td>
                <td>{{ record.va_creview_reason }}</td>
                <td>{{ record.va_creview_created_at.strftime('%Y-%m-%d %H:%M') if record.va_creview_created_at else 'N/A' }}</td>
                <td>
                <a href="#" class="btn btn-sm btn-outline-primary">Review</a>
                </td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
        </div>
    {% else %}
        <div class="text-center py-5">
        <p class="text-muted">No data available for the selected site.</p>
        </div>
    {% endif %}
    </div>
    -->
    <h3 class="text-primary mb-3 mt-4" style="font-size: 24px; font-weight: 600;">
    <i class="fas fa-users-cog me-2"></i> VA Coder Participation
    </h3>

    <div class="card shadow-sm border-0 rounded-3 mb-4">
    <div class="card-body"> 
        <div class="table-responsive">
        <table id="sitepiTable" class="table table-hover align-middle table-striped nowrap" style="width: 100%; min-width: 800px;">
            <thead class="table-light">
            <tr>
                <th class="ps-3 py-3">VA Coder</th>
                <th class="py-3">VA Coder Onboarded DigitVA</th>
                <th class="py-3 text-center">VA Submissions Coded</th>
                <th class="py-3 text-center">VA Submissions Marked as Not-Codeable</th>
            </tr>
            </thead>
            <tbody>
            {% for row in default_site_data.coder_kpis %}
            <tr>
                <td class="ps-3 fw-bold text-secondary">
                <div class="d-flex align-items-center">
                    <div class="bg-primary text-white me-2 rounded-circle d-flex justify-content-center align-items-center" style="width: 32px; height: 32px; font-size: 14px;">
                    {{ row[0][0] | upper if row[0] else 'U' }}
                    </div>
                    {{ row[0] }}
                </div>
                </td>
                
                <td>
                {% if row[1] %}
                    <span class="badge bg-success text-white px-3 py-2 rounded-pill shadow-sm">
                    <i class="fas fa-check me-1"></i> Onboarded
                    </span>
                {% else %}
                    <span class="badge bg-warning text-dark px-3 py-2 rounded-pill shadow-sm">
                    <i class="fas fa-clock me-1"></i> Pending
                    </span>
                {% endif %}
                </td>

                <td class="text-center">
                <span class="fw-bold text-dark">{{ row[2] }}</span>
                </td>
                
                <td class="text-center">
                {% if row[3] > 0 %}
                    <span class="fw-bold text-danger">{{ row[3] }}</span>
                {% else %}
                    <span class="fw-bold text-muted">{{ row[3] }}</span>
                {% endif %}
                </td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
        </div>
    </div>
    </div>
    """, site_data=site_data)


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
