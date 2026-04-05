import logging

# SQLWriteFilter is kept for the file handler on sqlalchemy.engine —
# it passes only write statements (INSERT/UPDATE/DELETE) to sql.log.
# Fast queries are further suppressed by the slow-query event hook in va_logger.py.
class SQLWriteFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return any(keyword in msg for keyword in ("INSERT", "UPDATE", "DELETE"))