import logging
import os
import time
from aiohttp import web as aweb
from poolguy import route
from jokes import replace_random_noun_chunk

logger = logging.getLogger(__name__)

TEST_CHAT_MAX_CHARS = 2000


def jerr(data, status):
    return aweb.json_response(data, status=status)


async def _json_body(request):
    try:
        body = await request.json()
    except Exception as e:
        logger.warning(f"invalid JSON body for {request.method} {request.path}: {e}")
        return None
    if not isinstance(body, dict):
        return None
    return body


def _ignore_truthy(val):
    if val is None:
        return False
    return str(val).strip().lower() not in ('0', 'false', '')


def _ws_connected(ws):
    socket = getattr(ws, '_socket', None)
    session_id = getattr(ws, '_session_id', None)
    if socket is None or session_id is None:
        return False
    return True


class WebApiMixin:
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
            "ws_connected": _ws_connected(self.ws),
            "uptime_seconds": int(time.time() - getattr(self, '_started_at', time.time())),
            "channels_total": len(chans),
            "channels_live": live_count,
            "ignores_total": ignores_total,
            "jokes_total": jokes_total,
            "joke_state": {
                "cooldown_seconds": self.jlimit,
                "seconds_since_last_joke": seconds_since_last_joke,
                "keyword_cooldown_remaining": keyword_cooldown_remaining,
                "random_counter": self.msg_since_joke,
                "random_next_at": self.next_joke_after,
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
        body = await _json_body(request)
        if body is None:
            return jerr({"status": False, "error": "missing or invalid JSON body"}, 400)
        login = (body.get('login') or '').strip().lstrip('@')
        if not login:
            return jerr({"status": False, "error": "missing 'login'"}, 400)
        try:
            users = await self.http.getUsers(logins=[login])
        except Exception as e:
            logger.exception(f"twitch user lookup failed for '{login}': {e}")
            return jerr({"status": False, "error": "twitch user lookup failed"}, 502)
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
        body = await _json_body(request)
        if body is None:
            return jerr({"status": False, "error": "missing or invalid JSON body"}, 400)
        login = (body.get('login') or '').strip().lstrip('@')
        if not login:
            return jerr({"status": False, "error": "missing 'login'"}, 400)
        try:
            users = await self.http.getUsers(logins=[login])
        except Exception as e:
            logger.exception(f"twitch user lookup failed for '{login}': {e}")
            return jerr({"status": False, "error": "twitch user lookup failed"}, 502)
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

    @route('/api/test/joke', method='POST')
    async def api_test_joke(self, request):
        body = await _json_body(request)
        if body is None:
            return jerr({"status": False, "error": "missing or invalid JSON body"}, 400)
        message = (body.get('message') or '').strip()
        if not message:
            return jerr({"status": False, "error": "missing 'message'"}, 400)
        jokes = await self._get_jokes()
        uid = self.http.user_id
        for key, joke in jokes.items():
            if key in message.lower():
                emote = await self.get_jemote(uid) if uid else self.default_jemote
                return self.app.response_json({"status": True, "reply": f"{joke}! {emote}", "matched_keyword": key})
        r = await replace_random_noun_chunk(message, "deez nutz")
        if not r:
            return self.app.response_json({"status": True, "reply": None, "matched_keyword": None})
        emote = await self.get_jemote(uid) if uid else self.default_jemote
        return self.app.response_json({"status": True, "reply": f"{r} {emote}", "matched_keyword": None})

    @route('/api/test/chat', method='POST')
    async def api_test_chat(self, request):
        body = await _json_body(request)
        if body is None:
            return jerr({"status": False, "error": "missing or invalid JSON body"}, 400)
        message = (body.get('message') or '').strip()
        if not message:
            return jerr({"status": False, "error": "missing 'message'"}, 400)
        if len(message) > TEST_CHAT_MAX_CHARS:
            return jerr({"status": False, "error": f"message exceeds the {TEST_CHAT_MAX_CHARS} character limit"}, 400)
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
