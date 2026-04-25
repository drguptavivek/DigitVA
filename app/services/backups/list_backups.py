import os
import traceback
from flask import current_app


def va_db_backup_listbackups():
    try:
        va_backup_dir = current_app.config["APP_BACKUP"]
        if not os.path.exists(va_backup_dir):
            print("App DB backup directory not found.")
            return []
        va_backups = sorted(
            [f for f in os.listdir(va_backup_dir) if f.endswith(".sql")], reverse=True
        )
        if not va_backups:
            print("App DB backups not found.")
        else:
            for i, b in enumerate(va_backups, 1):
                size = os.path.getsize(os.path.join(va_backup_dir, b))
                print(f"{i}. {b} ({size} bytes)")
        return va_backups
    except Exception as e:
        print(f"Failed to list app DB backups: {e}")
        print(traceback.format_exc())
        return []
