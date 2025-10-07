import os
import traceback
import subprocess
from app import db
from flask import current_app


def va_db_backup_restore(va_backup_path):
    try:
        if not os.path.exists(va_backup_path):
            print(f"App DB backup not found: {va_backup_path}")
            return
        va_db_url = current_app.config["SQLALCHEMY_DATABASE_URI"]
        db.session.remove()
        drop_cmd = [
            "psql",
            va_db_url,
            "-c",
            "DROP SCHEMA public CASCADE; CREATE SCHEMA public;",
        ]
        try:
            subprocess.run(drop_cmd, check=True, timeout=60)
        except subprocess.CalledProcessError:
            print("Failed to clear app DB schema and data.")
        except subprocess.TimeoutExpired:
            print("Failed to clear app DB schema and data.")
        cmd = ["psql", va_db_url, "-v", "ON_ERROR_STOP=1", "-f", va_backup_path]
        try:
            subprocess.run(cmd, check=True, timeout=60)
            print("App DB restored successfully.")
        except subprocess.CalledProcessError:
            print("App DB restore failed.")
        except subprocess.TimeoutExpired:
            print("App DB restore failed.")
    except Exception as e:
        print(f"App DB backup restoration failed unexpectedly: {e}")
        print(traceback.format_exc())
