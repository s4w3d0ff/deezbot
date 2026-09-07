import asyncio
import logging
import os
from poolguy import route
from logbuffer import _log_handler, LOG_MAXLEN

logger = logging.getLogger(__name__)


class WebManageMixin:
    @route('/api/logs')
    async def api_logs(self, request):
        lines = int(request.query.get('lines') or 200)
        lines = max(1, min(lines, LOG_MAXLEN))
        buf = _log_handler.buffer
        entries = list(buf)[-lines:]
        return self.app.response_json({
            "status": True,
            "total": len(buf),
            "oldest_seq": buf[0]['seq'] if buf else None,
            "newest_seq": buf[-1]['seq'] if buf else None,
            "entries": entries,
        })

    @route('/api/config')
    async def api_config(self, request):
        return self.app.response_json({
            "status": True,
            "web_host": self.web_host,
            "web_port": self.web_port,
            "jdelay": self.jdelay,
            "jlimit": self.jlimit,
            "loop_delay": self.loop_delay,
            "default_jemote": self.default_jemote,
            "channel_cache_ttl": self.channel_cache_ttl,
            "db_write_tables": list(self.db_write_tables),
            "log_buffer_size": _log_handler.buffer.maxlen,
            "ui": self.ui_cfg,
        })

    async def before_login(self):
        if not self.app.is_running():
            self.app.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.app.static_dirs = list(getattr(self, 'web_static_dirs', None) or ['ui'])
            await self.app.start()

    async def after_login(self):
        await self.add_task(self.deez_loop)

    async def deez_loop(self):
        logger.debug(f'deez_loop started')
        await asyncio.sleep(5)
        while self.loop_delay:
            try:
                await self.check_connections()
            except Exception as e:
                logger.exception(f"deez_loop Error:\n{e}")
            await asyncio.sleep(self.loop_delay)
        logger.warning(f'deez_loop stopped')
