import logging
import aiosqlite
from poolguy import route
from web_api import _json_body, jerr

logger = logging.getLogger(__name__)

DB_SENSITIVE_TABLES = ('tokens', 'queue')


class WebDbMixin:
    @route('/api/db/tables')
    async def api_db_tables(self, request):
        tables = []
        async with aiosqlite.connect(self.storage.db_path) as db:
            async with db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name") as cur:
                names = [row[0] async for row in cur]
            for name in names:
                if name in DB_SENSITIVE_TABLES:
                    continue
                clean = self.storage._clean_str(name)
                async with db.execute(f'SELECT count(*) FROM {clean}') as cur:
                    row = await cur.fetchone()
                tables.append({
                    "name": name,
                    "row_count": row[0] if row else 0,
                    "writable": clean in self.db_write_tables,
                })
        return self.app.response_json({"status": True, "tables": tables})

    @route('/api/db/table/{table}')
    async def api_db_table(self, request):
        table = self.storage._clean_str(request.match_info['table'])
        if table in DB_SENSITIVE_TABLES:
            return jerr({"status": False, "error": f"table '{table}' is not readable from the dashboard"}, 403)
        limit = int(request.query.get('limit') or 200)
        rows = await self.storage.query(table)
        return self.app.response_json({"status": True, "table": table, "rows": rows[:limit]})

    @route('/api/db/table/{table}', method='POST')
    async def api_db_table_insert(self, request):
        table = self.storage._clean_str(request.match_info['table'])
        if table not in self.db_write_tables:
            return jerr({"status": False, "error": f"table '{table}' is read-only"}, 403)
        body = await _json_body(request)
        if body is None:
            return jerr({"status": False, "error": "missing or invalid JSON body"}, 400)
        data = {k: str(v) for k, v in body.items()}
        if not data:
            return jerr({"status": False, "error": "empty row payload"}, 400)
        await self.storage.insert(table, data)
        logger.info(f"UI db insert into {table}: {data}")
        return self.app.response_json({"status": True, "inserted": data})

    @route('/api/db/table/{table}', method='DELETE')
    async def api_db_table_delete(self, request):
        table = self.storage._clean_str(request.match_info['table'])
        if table not in self.db_write_tables:
            return jerr({"status": False, "error": f"table '{table}' is read-only"}, 403)
        body = await _json_body(request)
        if body is None:
            return jerr({"status": False, "error": "missing or invalid JSON body"}, 400)
        where = body.get('where')
        params = tuple(body.get('params') or ())
        if not where:
            return jerr({"status": False, "error": "missing 'where' clause"}, 400)
        await self.storage.delete(table, where=where, params=params)
        logger.info(f"UI db delete from {table}: {where} {params}")
        return self.app.response_json({"status": True, "deleted_from": table})
