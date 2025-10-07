import sqlalchemy as sa
from app import create_app, db
from app.services import (
    va_data_sync_odkcentral,
    va_db_backup_create,
    va_db_backup_execute,
    va_db_initialise_researchprojects,
    va_db_initialise_researchsites,
    va_db_initialise_vaforms,
    va_db_initialise_vausers,
    va_form_addform,
    va_form_updateform,
    va_form_deleteform,
    va_mapping_fieldsitepi,
    va_mapping_fieldcoder,
    va_mapping_choice,
    va_mapping_summary,
    va_mapping_summaryflip,
    va_mapping_info,
    va_mapping_flip,
    va_mapping_icd,
    va_researchproject_addproject,
    va_researchproject_updateproject,
    va_researchproject_deleteproject,
    va_site_addsite,
    va_site_updatesite,
    va_site_deletesite,
    va_user_create,
    va_user_update,
    va_user_delete,
)

app = create_app()


@app.shell_context_processor
def make_shell_context():
    
    def va_initialise_platform():
        va_db_backup_create()
        db.drop_all()
        db.create_all()
        va_db_initialise_researchprojects()
        va_db_initialise_researchsites()
        va_db_initialise_vaforms()
        va_mapping_icd()
        va_mapping_fieldsitepi()
        va_mapping_fieldcoder()
        va_mapping_choice()
        va_mapping_summary()
        va_mapping_summaryflip()
        va_mapping_info()
        va_mapping_flip()
        va_data_sync_odkcentral()
        va_db_initialise_vausers()

    def va_updateall_maps():
        va_mapping_icd()
        va_mapping_fieldsitepi()
        va_mapping_fieldcoder()
        va_mapping_choice()
        va_mapping_summary()
        va_mapping_summaryflip()
        va_mapping_info()
        va_mapping_flip()
        
    def va_initiate_datasync():
        va_db_backup_create()
        va_data_sync_odkcentral()
        

    context = {
        "sa": sa,
        "db": db,
        "va_data_sync_odkcentral": va_data_sync_odkcentral,
        "va_db_backup_create": va_db_backup_create,
        "va_db_backup_execute": va_db_backup_execute,
        "va_db_initialise_researchprojects": va_db_initialise_researchprojects,
        "va_db_initialise_researchsites": va_db_initialise_researchsites,
        "va_db_initialise_vaforms": va_db_initialise_vaforms,
        "va_db_initialise_vausers": va_db_initialise_vausers,
        "va_form_addform": va_form_addform,
        "va_form_updateform": va_form_updateform,
        "va_form_deleteform": va_form_deleteform,
        "va_mapping_fieldsitepi": va_mapping_fieldsitepi,
        "va_mapping_fieldcoder": va_mapping_fieldcoder,
        "va_mapping_choice": va_mapping_choice,
        "va_mapping_summary": va_mapping_summary,
        "va_mapping_summaryflip": va_mapping_summaryflip,
        "va_mapping_info": va_mapping_info,
        "va_mapping_flip": va_mapping_flip,
        "va_mapping_icd": va_mapping_icd,
        "va_researchproject_addproject": va_researchproject_addproject,
        "va_researchproject_updateproject": va_researchproject_updateproject,
        "va_researchproject_deleteproject": va_researchproject_deleteproject,
        "va_site_addsite": va_site_addsite,
        "va_site_updatesite": va_site_updatesite,
        "va_site_deletesite": va_site_deletesite,
        "va_user_create": va_user_create,
        "va_user_update": va_user_update,
        "va_user_delete": va_user_delete,
        "va_initialise_platform": va_initialise_platform,
        "va_updateall_maps": va_updateall_maps,
        "va_initiate_datasync": va_initiate_datasync
    }
    return context


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
