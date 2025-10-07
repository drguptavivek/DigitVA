import logging


class SQLWriteFilter(logging.Filter):
    def filter(self, record):
        if any(
            keyword in record.getMessage() for keyword in ["INSERT", "UPDATE", "DELETE"]
        ):
            return True
        return False