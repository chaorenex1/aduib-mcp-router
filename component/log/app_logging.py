import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from aduib_app import AduibAIApp
from configs import config


def init_logging(app: AduibAIApp):
    if not logging.getLogger().hasHandlers():
        log_handlers: list[logging.Handler] = []
        sh = logging.StreamHandler(sys.stdout)
        log_handlers.append(sh)
        log_file = config.LOG_FILE
        if log_file:
            log_dir = os.path.join(app.app_home, "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_handlers.append(
                RotatingFileHandler(
                    filename=os.path.join(log_dir, log_file),
                    maxBytes=config.LOG_FILE_MAX_BYTES * 1024 * 1024,
                    backupCount=config.LOG_FILE_BACKUP_COUNT,
                )
            )
        logging.basicConfig(
            level=config.LOG_LEVEL,
            format=config.LOG_FORMAT,
            handlers=log_handlers
        )
        logging.root.setLevel(config.LOG_LEVEL)
        logging.root.addHandler(sh)
        log_tz = config.LOG_TZ
        if log_tz:
            from datetime import datetime

            import pytz

            timezone = pytz.timezone(log_tz)

            def time_converter(seconds):
                return datetime.fromtimestamp(seconds, tz=timezone).timetuple()

            for handler in logging.root.handlers:
                if handler.formatter:
                    handler.formatter.converter = time_converter
        logging.info("Logging initialized")
