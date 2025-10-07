from app.utils.va_user.va_user_02_variablevalidators import fail

def validate_project_code(project_code):
    if project_code and len(project_code) > 6:
        return fail(f"Project code '{project_code} length exceeds 6 characters.")
    return True