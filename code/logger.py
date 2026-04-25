import logging
import os
import sys

# Default log level
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
# Default flag to save raw data and SBE results
SAVE_DATA = os.environ.get("SAVE_DATA", "FALSE").upper() == "TRUE"

class Logger:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Logger, cls).__new__(cls)
            cls._instance._setup()
        return cls._instance

    def _setup(self):
        self.logger = logging.getLogger("Scorebot")
        self.logger.setLevel(LOG_LEVEL)
        
        # Avoid adding multiple handlers if setup is called multiple times
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stderr)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def debug(self, msg, *args, **kwargs):
        self.logger.debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self.logger.info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self.logger.error(msg, *args, **kwargs)

    def should_save_data(self):
        return SAVE_DATA

logger = Logger()
