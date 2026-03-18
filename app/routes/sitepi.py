import sqlalchemy as sa
from app import db
from flask_login import current_user, login_required
from flask import Blueprint, render_template, render_template_string, request
from app.utils.va_permission.va_permission_01_abortwithflash import va_permission_abortwithflash

sitepi = Blueprint("sitepi", __name__)


@sitepi.get("/")
@login_required
def dashboard():
    if not current_user.is_site_pi():
        va_permission_abortwithflash("No sites assigned for supervision.", 403)

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


@sitepi.get("/data")
@login_required
def sitepi_data():
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
