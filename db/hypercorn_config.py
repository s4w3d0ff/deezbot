import logging

_level = "INFO"

bind = ["localhost:5000"]

logconfig_dict = {
  "version": 1,
  "disable_existing_loggers": False,
  "handlers": {
      "console": {
          "class": "logging.StreamHandler",
          "level": _level,
          "formatter": "default",
          "stream": "ext://sys.stdout",
      },
  },
  "root": {"handlers": ["console"], "level": _level},
  "formatters": {
      "default": {
          "format": "%(asctime)s-%(levelname)s-[%(name)s] %(message)s",
          "datefmt": "%I:%M:%S%p",
      },
  },
}