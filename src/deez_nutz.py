import random
import asyncio
import logging
import time
import os
import aiosqlite
from poolguy import CommandBot, route
from config import loadYAML, DEFAULT_WRITE_TABLES
from logbuffer import _log_handler, LOG_MAXLEN
from jokes import configure_spacy, replace_random_noun_chunk, DEFAULT_SPACY_MODEL
from alerts import ChannelChatMessageAlert
from commands import CommandsMixin
from web_api import WebApiMixin, jerr, _ignore_truthy
from web_manage import WebManageMixin

logger = logging.getLogger(__name__)


class DeezBot(CommandBot, CommandsMixin, WebApiMixin, WebManageMixin):
    def __init__(self, cfg=None, *args, **kwargs):
        # Fetch sensitive data from environment variables
        client_id = os.getenv("DEEZ_CLIENT_ID")
        client_secret = os.getenv("DEEZ_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise ValueError("Environment variables DEEZ_CLIENT_ID and DEEZ_CLIENT_SECRET are required")
        cfg = dict(cfg or {})
        for key in ('scopes', 'channels', 'storage', 'browser', 'redirect_uri',
                    'jdelay', 'jlimit', 'loop_delay', 'default_jemote', 'spacy_model'):
            if key not in cfg and key in kwargs:
                cfg[key] = kwargs.pop(key)

        web_cfg = dict(cfg.get('web') or {})
        self.web_host = web_cfg.get('host', 'localhost')
        self.web_port = int(web_cfg.get('port', 5000))
        self.web_static_dirs = list(web_cfg.get('static_dirs') or ['ui'])
        _log_handler.resize(int(web_cfg.get('log_buffer_size') or LOG_MAXLEN))

        configure_spacy(cfg.get('spacy_model'))
        self.default_jemote = cfg.get('default_jemote') or 'Kappa'
        self.channel_cache_ttl = float((cfg.get('enrichment') or {}).get('channel_cache_ttl') or 60)
        self.db_write_tables = tuple(cfg.get('db_write_tables') or DEFAULT_WRITE_TABLES)
        self.ui_cfg = dict(cfg.get('ui') or {})

        pg_cfg = {key: cfg[key] for key in ('scopes', 'channels', 'storage', 'browser') if key in cfg}
        pg_cfg['redirect_uri'] = cfg.get('redirect_uri') or f"http://{self.web_host}:{self.web_port}/callback"
        pg_cfg['client_id'] = client_id
        pg_cfg['client_secret'] = client_secret
        alert_objs = kwargs.pop('alert_objs', None) or {'channel.chat.message': ChannelChatMessageAlert}
        super().__init__(twitch_config=pg_cfg, alert_objs=alert_objs, **kwargs)
        self.jdelay = list(cfg.get('jdelay') or [4, 15])
        self.jcount = 0
        self.jcountmax = random.randint(*self.jdelay)
        self.loop_delay = int(cfg.get('loop_delay') or 300)
        self.jlimit = float(cfg.get('jlimit') or 20)
        self.lastjoke = 0
        self._started_at = time.time()

    def _resetjcount(self):
        self.lastjoke = 0
        self.jcount = 0
        self.jcountmax = random.randint(*self.jdelay)

    async def get_jemote(self, u_id):
        chans = await self._get_channel_list()
        if u_id in chans:
           return chans[u_id]["jemote"]
        return self.default_jemote

    async def makeJoke(self, data):
        message = data['message']['text']
        u_id = data["broadcaster_user_id"]
        self.jcount += 1
        # keep from spamming jokes if keywords are being used
        jokes = await self._get_jokes()
        if time.time() - self.lastjoke >= self.jlimit:
            emote = await self.get_jemote(u_id)
            for key, joke in jokes.items():
                if key in message.lower():
                    self._resetjcount()
                    self.lastjoke = time.time()
                    return f"{joke}! {emote}"
        # make random joke
        if self.jcount >= self.jcountmax:
            emote = await self.get_jemote(u_id)
            r = replace_random_noun_chunk(message, "deez nutz")
            if r:
                self._resetjcount()
                self.lastjoke = time.time()
                return f"{r} {emote}"

    async def _update_user_ignore(self, user_id, ignore):
        await self.storage.insert("ignore", {"user_id": user_id, "ignore": ignore})
    
    async def _get_ignore_status(self, user_id):
        r = await self.storage.query("ignore", where="user_id = ?", params=(user_id,))
        try:
            return _ignore_truthy(r[0]["ignore"])
        except:
            return False

    async def _update_channel_list(self, user_id, config={}):
        if config == False:
            await self.storage.delete("channels", where="user_id = ?", params=(user_id,))
        else:
            await self.storage.insert("channels", {"user_id": user_id, **config})

    async def _get_channel_list(self):
        r = await self.storage.query("channels")
        return {row["user_id"]: row for row in r}
    
    async def _get_jokes(self):
        r = await self.storage.query("joke")
        return {row["keyword"]: row["joke"] for row in r}

    async def _enrich_channels(self):
        chans = await self._get_channel_list()
        if not getattr(self, '_chan_cached_at', 0) or time.monotonic() - self._chan_cached_at > self.channel_cache_ttl:
            info_map, live_map = {}, {}
            ids = list(chans.keys())
            if ids:
                try:
                    users = await self.http.getUsers(ids=ids)
                    for u in users:
                        info_map[u['id']] = {'login': u['login'], 'display_name': u['display_name']}
                except Exception as e:
                    logger.warning(f"Channel username enrichment failed: {e}")
                try:
                    streams = await self.http.getStreams(user_id=ids, type='live', first=100)
                    for s in streams:
                        live_map[s['id']] = {'is_live': True, 'viewers': s.get('viewer_count') or 0, 'title': s.get('title') or ''}
                except Exception as e:
                    logger.warning(f"Channel stream status check failed: {e}")
            self._chan_info_map, self._chan_live_map = info_map, live_map
            self._chan_cached_at = time.monotonic()
        out = {}
        for uid, row in chans.items():
            info = dict(row)
            info.update(self._chan_info_map.get(uid, {'login': None, 'display_name': None}))
            info.setdefault('is_live', False)
            info['viewers'] = 0
            info['title'] = ''
            live = self._chan_live_map.get(uid)
            if live:
                info.update(live)
            out[uid] = info
        return out

    async def _enrich_users(self, user_ids):
        users = {}
        try:
            for u in await self.http.getUsers(ids=list(user_ids)):
                users[u['id']] = {'login': u['login'], 'display_name': u['display_name']}
        except Exception as e:
            logger.warning(f"Ignore list username enrichment failed: {e}")
        return users
    
    #===================================================================================
    # Web UI + API ================================================================
    #===================================================================================
    @route('/api/db/tables')
    async def api_db_tables(self, request):
        tables = []
        async with aiosqlite.connect(self.storage.db_path) as db:
            async with db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name") as cur:
                names = [row[0] async for row in cur]
            for name in names:
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
        limit = int(request.query.get('limit') or 200)
        rows = await self.storage.query(table)
        return self.app.response_json({"status": True, "table": table, "rows": rows[:limit]})

    @route('/api/db/table/{table}', method='POST')
    async def api_db_table_insert(self, request):
        table = self.storage._clean_str(request.match_info['table'])
        if table not in self.db_write_tables:
            return jerr({"status": False, "error": f"table '{table}' is read-only"}, 403)
        body = await request.json()
        data = {k: str(v) for k, v in body.items()} if isinstance(body, dict) else {}
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
        body = await request.json()
        where = (body or {}).get('where')
        params = tuple(body.get('params') or ())
        if not where:
            return jerr({"status": False, "error": "missing 'where' clause"}, 400)
        await self.storage.delete(table, where=where, params=params)
        logger.info(f"UI db delete from {table}: {where} {params}")
        return self.app.response_json({"status": True, "deleted_from": table})

    async def connected_channels(self):
        r = await self.http.getEventSubs(status='enabled')
        return {str(i["condition"]["broadcaster_user_id"]): i for i in r['data']}
    
    async def check_connections(self):
        connnected_channels = await self.connected_channels()
        connected_ids = set(connnected_channels.keys())
        logger.warning(f"Current connections:\n{connected_ids}")
        l = await self._get_channel_list()
        live_r = await self.http.getStreams(user_id=list(l.keys()), type='live') if l else []
        live_list = [chan["user_id"] for chan in live_r]
        live_list += [str(self.http.user_id)]
        disconnect_from = list(connected_ids - set(live_list))
        connect_to = list(set(live_list) - connected_ids)
        if disconnect_from:
            for chan_id in disconnect_from:
                if chan_id == str(self.http.user_id):
                    continue
                r = await self.http.deleteEventSub(connnected_channels[chan_id]['id'])
                if not r:
                    logger.error(f"Couldn't disconnect from {connnected_channels[chan_id]}")
            logger.warning(f"Disconnected from:\n{disconnect_from}")
        if connect_to:
            for chan_id in connect_to:
                try:
                    r = await self.ws.create_event_sub('channel.chat.message', chan_id)
                except:
                    logger.exception(f"Couldn't connect to {chan_id}:\n")
            logger.warning(f"Connected to:\n{connect_to}")


if __name__ == '__main__':
    from rich.logging import RichHandler
    logging.basicConfig(
        format='%(message)s',
        datefmt="%X",
        level=logging.INFO,
        handlers=[RichHandler(rich_tracebacks=True)]
    )
    bot = DeezBot(loadYAML('cfg.yaml'))
    asyncio.run(bot.start(hold=True))
