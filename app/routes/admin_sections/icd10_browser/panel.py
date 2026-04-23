from .common import admin, render_template, role_required


@admin.get("/panels/icd10-browser")
@role_required("admin")
def admin_panel_icd10_browser():
    return render_template("admin/panels/icd10_browser.html")
