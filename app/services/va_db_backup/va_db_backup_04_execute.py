import os
import traceback
from flask import current_app
from app.services.va_db_backup.va_db_backup_01_create import va_db_backup_create
from app.services.va_db_backup.va_db_backup_02_restore import va_db_backup_restore
from app.services.va_db_backup.va_db_backup_03_listbackups import va_db_backup_listbackups


def va_db_backup_execute():
    try:
        print("MINErVA DB Backup Tool")
        print("1. Create backup")
        print("2. List backups")
        print("3. Restore backup")
        choice = input("Enter choice (1-3): ").strip()
        if choice == "1":
            va_db_backup_create()
        elif choice == "2":
            va_db_backup_listbackups()
        elif choice == "3":
            va_backups = va_db_backup_listbackups()
            if not va_backups:
                return
            try:
                index = int(input("Enter VA backup number to restore: ")) - 1
                va_backup_file = os.path.join(
                    current_app.config["APP_BACKUP"], va_backups[index]
                )
                va_db_backup_restore(va_backup_file)
            except (ValueError, IndexError):
                print("Invalid selection for restoration.")
        else:
            print("Invalid choice. Please enter 1, 2, or 3.")
    except Exception as e:
        print(f"Unexpected error in app DB backup menu: {e}")
        print(traceback.format_exc())
