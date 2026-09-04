import os
import sys
import socket
import asyncio
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

os.environ['DEEZ_CLIENT_ID'] = 'test'
os.environ['DEEZ_CLIENT_SECRET'] = 'test'

from aiohttp.test_utils import TestClient, TestServer
from poolguy.core.storage import SQLiteStorage

import deez_nutz


def freeport():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def make_bot(tmp):
    bot = deez_nutz.DeezBot(
        redirect_uri='http://localhost:5000/callback',
        scopes=['user:read:chat', 'user:write:chat'],
        storage=SQLiteStorage(os.path.join(tmp, 'twitch.db')),
        channels={'channel.chat.message': None},
        jdelay=(1, 2),
        loop_delay=3600,
    )
    bot._setup()
    bot.app.base_dir = os.path.dirname(os.path.abspath(__file__)) + '/..'
    bot.app.static_dirs = ['ui']
    bot.app.host = '127.0.0.1'
    bot.app.port = freeport()
    return bot


def run_test(bot, probe):
    async def main():
        bot.app.add_static_dirs()
        client = TestClient(TestServer(bot.app.app))
        await client.start_server()
        try:
            return await probe(client)
        finally:
            await client.close()
    asyncio.run(main())


def test_before_login_starts_steady_state_server(tmp_path):
    bot = make_bot(str(tmp_path))

    async def main():
        assert not bot.app.is_running()
        try:
            await bot.before_login()
            assert bot.app.is_running(), 'web server did not start in steady state'
            await asyncio.sleep(0.2)
        finally:
            if bot.app.is_running():
                await bot.app.stop()
    asyncio.run(main())


def test_status_endpoint(tmp_path):
    bot = make_bot(str(tmp_path))

    async def probe(client):
        r = await client.get('/api/status')
        assert r.status == 200
        body = await r.json()
        assert body['authenticated'] is False
        assert body['user_id'] is None
        assert body['ws_connected'] is False
        assert body['channels'] == {}

    run_test(bot, probe)


def test_joke_keyword_hit(tmp_path):
    bot = make_bot(str(tmp_path))
    asyncio.run(bot.storage.insert('joke', {'keyword': 'fitness', 'joke': 'dick fit'}))

    async def probe(client):
        r = await client.post('/api/test/joke', json={'message': 'my FITNESS journey'})
        assert r.status == 200
        body = await r.json()
        assert body['matched_keyword'] == 'fitness'
        assert 'dick fit' in body['reply']

    run_test(bot, probe)


def test_joke_spacy_miss_and_stateless(tmp_path):
    bot = make_bot(str(tmp_path))
    asyncio.run(bot.storage.insert('joke', {'keyword': 'zzzznotpresent', 'joke': 'nope'}))

    async def probe(client):
        before = (bot.jcount, bot.lastjoke)
        r = await client.post('/api/test/joke', json={'message': '1 2 3'})
        assert r.status == 200
        body = await r.json()
        assert body['reply'] is None
        assert (bot.jcount, bot.lastjoke) == before

    run_test(bot, probe)


def test_joke_missing_message_400(tmp_path):
    bot = make_bot(str(tmp_path))

    async def probe(client):
        r = await client.post('/api/test/joke', json={})
        assert r.status == 400

    run_test(bot, probe)


def test_db_tables_listing_and_flags(tmp_path):
    bot = make_bot(str(tmp_path))
    asyncio.run(bot.storage.insert('joke', {'keyword': 'fitness', 'joke': 'dick fit'}))
    asyncio.run(bot.storage.save_token('twitch', {'token_json': '{}'}))

    async def probe(client):
        r = await client.get('/api/db/tables')
        assert r.status == 200
        tables = {t['name']: t for t in (await r.json())['tables']}
        assert 'joke' in tables and 'tokens' in tables
        assert tables['joke']['writable'] is True
        assert tables['joke']['row_count'] == 1
        assert tables['tokens']['writable'] is False

    run_test(bot, probe)


def test_db_roundtrip_insert_get_delete(tmp_path):
    bot = make_bot(str(tmp_path))

    async def probe(client):
        r = await client.post('/api/db/table/joke', json={'keyword': 'tulip', 'joke': 'deez nutz on yo head'})
        assert r.status == 200

        r = await client.get('/api/db/table/joke')
        rows = (await r.json())['rows']
        match = [row for row in rows if row['keyword'] == 'tulip']
        assert len(match) == 1 and match[0]['joke'] == 'deez nutz on yo head'

        r = await client.delete('/api/db/table/joke', json={'where': 'keyword = ?', 'params': ['tulip']})
        assert r.status == 200

        rows = (await (await client.get('/api/db/table/joke')).json())['rows']
        assert not [row for row in rows if row['keyword'] == 'tulip']

    run_test(bot, probe)


def test_db_write_whitelist_403(tmp_path):
    bot = make_bot(str(tmp_path))

    async def probe(client):
        r = await client.post('/api/db/table/tokens', json={'name': 'x', 'token_json': '{}'})
        assert r.status == 403
        r = await client.delete('/api/db/table/queue', json={'where': 'name = ?', 'params': ['x']})
        assert r.status == 403
        r = await client.get('/api/db/table/tokens')
        assert r.status == 200

    run_test(bot, probe)


def test_index_and_static(tmp_path):
    bot = make_bot(str(tmp_path))

    async def probe(client):
        r = await client.get('/')
        assert r.status == 200
        assert 'deezbot' in (await r.text())
        r = await client.get('/ui/app.js')
        assert r.status == 200
        r = await client.get('/ui/style.css')
        assert r.status == 200

    run_test(bot, probe)


def test_chat_endpoint_400_and_own_channel_only(tmp_path):
    bot = make_bot(str(tmp_path))
    sent = []

    async def fake_send(message, broadcaster_id=None):
        sent.append((message, broadcaster_id or 'OWN'))
        return [{'is_sent': True}]

    bot.http.sendChatMessage = fake_send

    async def probe(client):
        r = await client.post('/api/test/chat', json={})
        assert r.status == 400
        r = await client.post('/api/test/chat', json={'message': 'hello world'})
        assert r.status == 200
        body = await r.json()
        assert body['sent_chunks'] == 1
        assert sent and all(broadcaster == 'OWN' for _, broadcaster in sent)

    run_test(bot, probe)


def test_chat_chunking_400_chars(tmp_path):
    bot = make_bot(str(tmp_path))
    chunks = []

    async def fake_send(message, broadcaster_id=None):
        chunks.append(message)
        return [{'is_sent': True}]

    bot.http.sendChatMessage = fake_send

    async def probe(client):
        message = ' '.join(['word%d' % i for i in range(120)])
        r = await client.post('/api/test/chat', json={'message': message})
        assert r.status == 200
        body = await r.json()
        assert body['sent_chunks'] > 1
        assert all(len(c) <= 500 for c in chunks)

    run_test(bot, probe)
