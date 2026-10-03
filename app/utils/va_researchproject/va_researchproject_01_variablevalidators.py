def fail(reason):
    """Print a shell helper's validation failure and return False."""
    print(f"Failed [{reason}]")
    return False


def validate_project_code(project_code):
    if project_code and len(project_code) > 6:
        return fail(f"Project code '{project_code} length exceeds 6 characters.")
    return True