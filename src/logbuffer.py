import logging
import time
from collections import deque
import itertools

LOG_MAXLEN = 1000


class LogBufferHandler(logging.Handler):
    def __init__(self, maxlen=LOG_MAXLEN):
        super().__init__()
        self.buffer = deque(maxlen=maxlen)
        self._seq = itertools.count(1)

    def resize(self, maxlen):
        self.buffer = deque(self.buffer, maxlen=maxlen)

    def emit(self, record):
        self.buffer.append({
            'seq': next(self._seq),
            'ts': time.strftime('%H:%M:%S', time.localtime(record.created)),
            'level': logging.getLevelName(record.levelno),
            'name': record.name,
            'msg': record.getMessage()[:500],
        })


_log_handler = LogBufferHandler()
logging.getLogger().addHandler(_log_handler)
