import os
import subprocess
import traceback
from app import db
from flask import current_app
from datetime import datetime


def va_db_backup_create():
    try:
        va_backup_dir = current_app.config["APP_BACKUP"]
        va_db_url = current_app.config["SQLALCHEMY_DATABASE_URI"]
        os.makedirs(va_backup_dir, exist_ok=True)
        va_all_backups = [
            os.path.join(va_backup_dir, f)
            for f in os.listdir(va_backup_dir)
            if f.endswith(".sql")
        ]
        va_all_backups.sort(key=os.path.getmtime, reverse=True)
        for va_old_backup in va_all_backups[9:]:
            try:
                os.remove(va_old_backup)
                print("Warning [Maintaining last 10 backups only].")
            except Exception as e:
                print(f"Failed [Could not delete old backups '{va_old_backup}': {e}].")
                print(traceback.format_exc())
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        va_backup_file = f"minerva_db_backup_{timestamp}.sql"
        va_backup_path = os.path.join(va_backup_dir, va_backup_file)
        db.session.remove()
        cmd = [
            "pg_dump",
            "--no-owner",
            "--no-privileges",
            va_db_url,
            "-f",
            va_backup_path,
        ]
        try:
            subprocess.run(cmd, check=True, timeout=60)
            print("App DB backup created.")
        except subprocess.CalledProcessError:
            print("App DB backup failed.")
        except subprocess.TimeoutExpired:
            print("App DB backup failed.")
    except Exception as e:
        print(f"App DB backup failed unexpectedly: {e}")
        print(traceback.format_exc())
        return None
