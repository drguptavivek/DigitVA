from collections import OrderedDict
from app.utils.va_mapping.va_mapping_04_summary import va_mapping_summary
from app.utils.va_mapping.va_mapping_05_summaryflip import va_mapping_summaryflip


def va_preprocess_summcatenotification(va_data):
    summary_list = []
    category_notification = OrderedDict()
    special_summary_ids = ["Id10121", "Id10122", "Id10120", "Id10436"]

    try:
        for category in va_mapping_summary:
            category_notification[category] = {"count": 0}
        for category, sub_dict in va_mapping_summary.items():
            for va_id, va_summarylabel in sub_dict.items():
                if va_id in va_data:
                    va_response = va_data.get(va_id)
                    condition1 = (
                        va_summarylabel in va_mapping_summaryflip and va_response == "no"
                    )
                    condition2 = (
                        va_summarylabel not in va_mapping_summaryflip
                        and va_response == "yes"
                    )
                    condition3 = va_id not in special_summary_ids
                    condition4 = va_id in special_summary_ids
                    if (condition1 or condition2) and condition3:
                        summary_list.append(va_summarylabel)
                        category_notification[category]["count"] += 1
                    elif condition4:
                        summary_list.append(
                            f"{va_summarylabel}: {va_response}"
                        ) if va_response else None
    except Exception as e:
        raise Exception(
            f"VA Submission ({va_data.get('sid')}): Could not produce the category count notifications and summary for the submission. Error: {e}"
        )

    return summary_list, category_notification
