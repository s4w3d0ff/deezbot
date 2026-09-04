import spacy
import random
import asyncio
import logging
import time
import os
import aiosqlite
from aiohttp import web as aweb
from poolguy import CommandBot, Alert, rate_limit, command, route
from config import loadYAML, DEFAULT_WRITE_TABLES
from logbuffer import _log_handler, LOG_MAXLEN

logger = logging.getLogger(__name__)

DEFAULT_SPACY_MODEL = 'en_core_web_sm'
_nlp = None
_spacy_model = None


def configure_spacy(model):
    global _nlp, _spacy_model
    if model != _spacy_model:
        _spacy_model = model or DEFAULT_SPACY_MODEL
        _nlp = None


def get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load(_spacy_model or DEFAULT_SPACY_MODEL)
    return _nlp


def jerr(data, status):
    return aweb.json_response(data, status=status)

def _ignore_truthy(val):
    if val is None:
        return False
    return str(val).strip().lower() not in ('0', 'false', '')


def replace_random_noun_chunk(text, replacement="these walnuts"):
    """Uses spacy to find all noun 'chunks' <text>. Then replaces a random noun chunk with the <replacement>. Returns result as string"""
    doc = get_nlp()(text)
    noun_chunks = list(doc.noun_chunks)
    if not noun_chunks:
        return None
    
    if len(noun_chunks) > 1:
        del noun_chunks[0]
    
    to_replace = random.choice(noun_chunks)
    start = to_replace.start_char
    end = to_replace.end_char
    out = text[:start] + replacement + text[end:]
    
    if out.strip() == replacement.strip():
        return None
        
    logger.debug(f"[replace_random_noun_chunk] {text} -> {out}")
    return out

class ChannelChatMessageAlert(Alert):
    store = False
    queue_skip = True
    """channel.chat.message"""
    async def process(self):
        if int(self.bot.http.user_id) == int(self.data["chatter_user_id"]):
            return
        if await self.bot.command_check(self.data):
            return
        if await self.bot._get_ignore_status(self.data["chatter_user_id"]):
            return
        try:
            r = await self.bot.makeJoke(self.data)
            if r:
                m = await self.bot.send_chat(r, self.data["broadcaster_user_id"])
                logger.info(f'{self.data["broadcaster_user_login"]}: {r} {m}')
        except:
            logger.exception(f"Error in process_message():\n")
            raise


class DeezBot(CommandBot):
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
    
    def _is_channel_owner(self, user, channel):
        return int(channel["broadcaster_id"]) == int(user["user_id"])
    
    def _is_own_channel(self, user, channel):
        return int(channel["broadcaster_id"]) == int(self.http.user_id)

    @command(name="jemote")
    @rate_limit(calls=1, period=15)
    async def cmd_jemote(self, user, channel, args):
        """ Changes the jemote for the channel or user calling the command """
        if self._is_channel_owner(user, channel) or self._is_own_channel(user, channel):
            emote = args[0]
            try:
                await self._update_channel_list(user["user_id"], config={"jemote": emote})
                await self.send_chat(
                        f"{emote} I like it @{user['username']}", 
                        channel["broadcaster_id"]
                    )
                logger.info(f'Changed {user["username"]} emote: {emote}')
            except:
                logger.exception(f"\n")

    @command(name="join")
    @rate_limit(calls=1, period=15)
    async def cmd_join(self, user, channel, args):
        """ Adds the user calling the command to the channel list """
        if self._is_own_channel(user, channel):
            try:
                await self._update_channel_list(user["user_id"], config={
                        "jemote": self.default_jemote
                    })
                await self.send_chat(
                        f":3 @{user['username']}", 
                        channel["broadcaster_id"]
                    )
                logger.info(f'Joining channel: {user["user_id"]}({user["username"]})')
            except:
                logger.exception(f"\n")

    @command(name="leave")
    @rate_limit(calls=1, period=15)
    async def cmd_leave(self, user, channel, args):
        """ Removes the bot from the channel if the channel owner calls the command """
        if self._is_channel_owner(user, channel) or self._is_own_channel(user, channel):
            try:
                await self._update_channel_list(user["user_id"], config=False)
                await self.send_chat(
                        f"PeaceOut @{user['username']}", 
                        channel["broadcaster_id"]
                    )
                logger.info(f'Leaving channel: {user["user_id"]}({user["username"]})')
            except:
                logger.exception(f"\n")

    @command(name="ignore")
    @rate_limit(calls=1, period=15)
    async def cmd_ignore(self, user, channel, args):
        """ Adds the user calling the command to the ignore list """
        try:
            await self._update_user_ignore(user["user_id"], True)
            await self.send_chat(
                    f"I'm notListening to you @{user['username']}", 
                    channel["broadcaster_id"]
                )
            logger.info(f'Added {user["user_id"]}({user["username"]}) to ignore list')
        except:
            logger.exception(f"\n")

    @command(name="unignore")
    @rate_limit(calls=1, period=15)
    async def cmd_unignore(self, user, channel, args):
        """ Removes the calling user from the ignore list """
        try:
            await self._update_user_ignore(user["user_id"], False)
            await self.send_chat(
                        f"I'm Listening to you @{user['username']}", 
                        channel["broadcaster_id"]
                    )
            logger.info(f"Removed {user['user_id']}({user['username']}) from ignore list")
        except:
            logger.exception(f"\n")

    #===================================================================================
    # Web UI + API ================================================================
    #===================================================================================
    @route('/')
    async def ui_index(self, request):
        return await self.app.response_html(os.path.join(self.app.base_dir, 'ui', 'index.html'))

    @route('/api/status')
    async def api_status(self, request):
        token = await self.storage.get_token('twitch') or {}
        chans = await self._enrich_channels()
        username = None
        try:
            users = await self.http.getUsers(ids=[str(self.http.user_id)]) if self.http.user_id else []
            username = users[0]['login'] if users else None
        except Exception as e:
            logger.warning(f"Bot username lookup failed: {e}")
        live_count = sum(1 for c in chans.values() if c.get('is_live'))
        ignores_total = len(await self.storage.query("ignore"))
        jokes_total = len(await self._get_jokes())
        now = time.time()
        seconds_since_last_joke = int(now - self.lastjoke) if self.lastjoke else None
        keyword_cooldown_remaining = max(0, int(self.jlimit - (now - self.lastjoke))) if self.lastjoke else 0
        return self.app.response_json({
            "authenticated": bool(self.http.user_id),
            "user_id": str(self.http.user_id) if self.http.user_id else None,
            "username": username,
            "token_expires_time": token.get('expires_time'),
            "ws_connected": self.ws._socket is not None and self.ws._session_id is not None,
            "uptime_seconds": int(time.time() - getattr(self, '_started_at', time.time())),
            "channels_total": len(chans),
            "channels_live": live_count,
            "ignores_total": ignores_total,
            "jokes_total": jokes_total,
            "joke_state": {
                "cooldown_seconds": self.jlimit,
                "seconds_since_last_joke": seconds_since_last_joke,
                "keyword_cooldown_remaining": keyword_cooldown_remaining,
                "random_counter": self.jcount,
                "random_next_at": self.jcountmax,
            },
        })

    @route('/api/channels')
    async def api_channels(self, request):
        chans = await self._enrich_channels()
        rows = sorted(chans.values(), key=lambda c: (not c.get('is_live'), str(c.get('login') or '')))
        return self.app.response_json({
            "status": True,
            "total": len(rows),
            "live": sum(1 for r in rows if r.get('is_live')),
            "channels": rows,
        })

    @route('/api/channels', method='POST')
    async def api_channels_add(self, request):
        body = await request.json()
        login = (body.get('login') or '').strip().lstrip('@')
        if not login:
            return jerr({"status": False, "error": "missing 'login'"}, 400)
        users = await self.http.getUsers(logins=[login])
        if not users:
            return jerr({"status": False, "error": f"twitch user '{login}' not found"}, 404)
        u = users[0]
        await self.storage.insert("channels", {"user_id": str(u['id']), "jemote": body.get('jemote') or self.default_jemote})
        logger.info(f"UI added channel {u['login']} ({u['id']})")
        return self.app.response_json({"status": True, "added": {"user_id": u['id'], "login": u['login']}})

    @route('/api/ignores')
    async def api_ignores(self, request):
        rows = await self.storage.query("ignore")
        users = await self._enrich_users([r['user_id'] for r in rows]) if rows else {}
        out = []
        for r in rows:
            uid = r['user_id']
            info = users.get(uid, {'login': None, 'display_name': None})
            out.append({'user_id': uid, **info, 'ignored': _ignore_truthy(r.get('ignore'))})
        return self.app.response_json({"status": True, "total": len(out), "users": out})

    @route('/api/ignores', method='POST')
    async def api_ignores_add(self, request):
        body = await request.json()
        login = (body.get('login') or '').strip().lstrip('@')
        if not login:
            return jerr({"status": False, "error": "missing 'login'"}, 400)
        users = await self.http.getUsers(logins=[login])
        if not users:
            return jerr({"status": False, "error": f"twitch user '{login}' not found"}, 404)
        u = users[0]
        await self._update_user_ignore(str(u['id']), True)
        logger.info(f"UI ignored user {u['login']} ({u['id']})")
        return self.app.response_json({"status": True, "ignored": {"user_id": u['id'], "login": u['login']}})

    @route('/api/commands')
    async def api_commands(self, request):
        aliases = set()
        for cmd in self._commands.values():
            aliases.update(cmd.get('aliases') or [])
        out = []
        for name, cmd in sorted(self._commands.items()):
            if name in aliases:
                continue
            out.append({'name': name, 'aliases': cmd.get('aliases') or [], 'help': (cmd.get('help') or '').strip()})
        return self.app.response_json({"status": True, "total": len(out), "commands": out})

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

    @route('/api/test/joke', method='POST')
    async def api_test_joke(self, request):
        body = await request.json()
        message = (body.get('message') or '').strip()
        if not message:
            return jerr({"status": False, "error": "missing 'message'"}, 400)
        jokes = await self._get_jokes()
        for key, joke in jokes.items():
            if key in message.lower():
                emote = await self.get_jemote(self.http.user_id)
                return self.app.response_json({"status": True, "reply": f"{joke}! {emote}", "matched_keyword": key})
        r = replace_random_noun_chunk(message, "deez nutz")
        if not r:
            return self.app.response_json({"status": True, "reply": None, "matched_keyword": None})
        emote = await self.get_jemote(self.http.user_id)
        return self.app.response_json({"status": True, "reply": f"{r} {emote}", "matched_keyword": None})

    @route('/api/test/chat', method='POST')
    async def api_test_chat(self, request):
        body = await request.json()
        message = (body.get('message') or '').strip()
        if not message:
            return jerr({"status": False, "error": "missing 'message'"}, 400)
        out = ""
        sent_chunks = 0
        for word in message.split(" "):
            if len(out) + len(word) > 400:
                await self.http.sendChatMessage(out.strip())
                sent_chunks += 1
                out = word + " "
            else:
                out += word + " "
        if len(out) > 0:
            await self.http.sendChatMessage(out.strip())
            sent_chunks += 1
        logger.info(f"UI test chat sent {sent_chunks} chunk(s) to own channel")
        return self.app.response_json({"status": True, "sent_chunks": sent_chunks})

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

    #===================================================================================
    #===================================================================================
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
                logger.error("deez_loop Error:\n{e}")
            await asyncio.sleep(self.loop_delay)
        logger.warning(f'deez_loop stopped')
    #===================================================================================
    #===================================================================================

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
