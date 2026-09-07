import os
import sys
import socket
import asyncio
import logging
import random
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

os.environ['DEEZ_CLIENT_ID'] = 'test'
os.environ['DEEZ_CLIENT_SECRET'] = 'test'

from aiohttp.test_utils import TestClient, TestServer
from poolguy.core.storage import SQLiteStorage

import bot as deezbot

logger = logging.getLogger('deeztest')


def freeport():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def make_bot(tmp):
    bot = deezbot.DeezBot(
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
    asyncio.run(bot.storage.insert('joke', {'keyword': 'fitness', 'joke': 'dick fit'}))
    asyncio.run(bot.storage.insert('channels', {'user_id': '1000000', 'jemote': 'Kappa'}))

    async def probe(client):
        r = await client.get('/api/status')
        assert r.status == 200
        body = await r.json()
        assert body['authenticated'] is False
        assert body['user_id'] is None
        assert body['username'] is None
        assert body['ws_connected'] is False
        assert body['uptime_seconds'] >= 0
        assert body['channels_total'] == 1
        assert body['channels_live'] == 0

    run_test(bot, probe)


def test_channels_enriched(tmp_path):
    bot = make_bot(str(tmp_path))
    asyncio.run(bot.storage.insert('channels', {'user_id': '2000001', 'jemote': 'GOTTEM'}))
    asyncio.run(bot.storage.insert('channels', {'user_id': '2000002', 'jemote': 'Kappa'}))

    async def fake_get_users(ids=None, logins=None):
        return [
            {'id': '2000001', 'login': 'livestreamer', 'display_name': 'LiveStreamer'},
            {'id': '2000002', 'login': 'offstreamer', 'display_name': 'OffStreamer'},
        ]

    async def fake_get_streams(first=None, **kwargs):
        return [{'id': '999999', 'user_id': '2000001', 'viewer_count': 42, 'title': 'just deezing'}]

    bot.http.getUsers = fake_get_users
    bot.http.getStreams = fake_get_streams

    async def probe(client):
        r = await client.get('/api/channels')
        assert r.status == 200
        body = await r.json()
        assert body['total'] == 2 and body['live'] == 1
        by_id = {c['user_id']: c for c in body['channels']}
        live = by_id['2000001']
        assert live['is_live'] is True
        assert live['viewers'] == 42
        assert live['title'] == 'just deezing'
        assert live['login'] == 'livestreamer'
        assert live['jemote'] == 'GOTTEM'
        off = by_id['2000002']
        assert off['is_live'] is False and off['viewers'] == 0 and off['title'] == ''
        assert body['channels'][0]['user_id'] == '2000001'
        assert bot._chan_live_map.keys() == {'2000001'}

    run_test(bot, probe)


def test_ignores_enriched(tmp_path):
    bot = make_bot(str(tmp_path))
    asyncio.run(bot.storage.insert('ignore', {'user_id': '3000001', 'ignore': 'True'}))
    asyncio.run(bot.storage.insert('ignore', {'user_id': '3000002', 'ignore': 'False'}))

    async def fake_get_users(ids=None, logins=None):
        return [{'id': '3000001', 'login': 'spammer', 'display_name': 'SpamLord'}]

    bot.http.getUsers = fake_get_users

    async def probe(client):
        r = await client.get('/api/ignores')
        assert r.status == 200
        body = await r.json()
        assert body['total'] == 2
        by_id = {u['user_id']: u for u in body['users']}
        assert by_id['3000001']['login'] == 'spammer'
        assert by_id['3000001']['display_name'] == 'SpamLord'
        assert by_id['3000002']['login'] is None

    run_test(bot, probe)


def test_status_channel_counts(tmp_path):
    bot = make_bot(str(tmp_path))
    asyncio.run(bot.storage.insert('channels', {'user_id': '4000001', 'jemote': 'Kappa'}))

    async def fake_get_users(ids=None, logins=None):
        return [{'id': '4000001', 'login': 'somechan', 'display_name': 'SomeChan'}]

    async def fake_get_streams(first=None, **kwargs):
        return []

    bot.http.getUsers = fake_get_users
    bot.http.getStreams = fake_get_streams

    async def probe(client):
        r = await client.get('/api/status')
        body = await r.json()
        assert body['channels_total'] == 1
        assert body['channels_live'] == 0
        assert body['uptime_seconds'] >= 0

    run_test(bot, probe)


def test_status_joke_state(tmp_path):
    bot = make_bot(str(tmp_path))
    asyncio.run(bot.storage.insert('joke', {'keyword': 'fitness', 'joke': 'dick fit'}))
    import time as _time
    bot.lastjoke = _time.time() - 5

    async def probe(client):
        body = await (await client.get('/api/status')).json()
        js = body['joke_state']
        assert js['cooldown_seconds'] == bot.jlimit
        assert 4 <= js['seconds_since_last_joke'] <= 6
        assert 0 < js['keyword_cooldown_remaining'] <= bot.jlimit - 5 + 1
        assert js['random_counter'] == 0 and js['random_next_at'] >= 1

    run_test(bot, probe)


def test_add_channel_resolves_login(tmp_path):
    bot = make_bot(str(tmp_path))

    async def fake_get_users(ids=None, logins=None):
        if logins == ['newstreamer']:
            return [{'id': '6000001', 'login': 'newstreamer', 'display_name': 'NewStreamer'}]
        return []

    bot.http.getUsers = fake_get_users

    async def probe(client):
        r = await client.post('/api/channels', json={})
        assert r.status == 400

        r = await client.post('/api/channels', json={'login': 'ghostuser'})
        assert r.status == 404

        r = await client.post('/api/channels', json={'login': '@newstreamer', 'jemote': 'POG'})
        assert r.status == 200
        body = await r.json()
        assert body['added'] == {'user_id': '6000001', 'login': 'newstreamer'}

        rows = (await (await client.get('/api/db/table/channels')).json())['rows']
        match = [row for row in rows if row['user_id'] == '6000001']
        assert len(match) == 1 and match[0]['jemote'] == 'POG'

    run_test(bot, probe)


def test_add_ignore_resolves_login(tmp_path):
    bot = make_bot(str(tmp_path))

    async def fake_get_users(ids=None, logins=None):
        if '7000001' in [str(i) for i in (ids or [])] + [str(l) for l in (logins or [])]:
            return [{'id': '7000001', 'login': 'spammy', 'display_name': 'SpamLord'}]
        if logins == ['spammy']:
            return [{'id': '7000001', 'login': 'spammy', 'display_name': 'SpamLord'}]
        return []

    bot.http.getUsers = fake_get_users

    async def probe(client):
        r = await client.post('/api/ignores', json={})
        assert r.status == 400
        r = await client.post('/api/ignores', json={'login': 'ghostuser'})
        assert r.status == 404

        r = await client.post('/api/ignores', json={'login': 'spammy'})
        assert r.status == 200

        body = (await (await client.get('/api/ignores')).json())
        by_id = {u['user_id']: u for u in body['users']}
        assert by_id['7000001']['ignored'] is True and by_id['7000001']['login'] == 'spammy'

    run_test(bot, probe)


def test_commands_listing(tmp_path):
    bot = make_bot(str(tmp_path))

    async def probe(client):
        r = await client.get('/api/commands')
        assert r.status == 200
        body = await r.json()
        names = [c['name'] for c in body['commands']]
        assert set(names) >= {'jemote', 'join', 'leave', 'ignore', 'unignore'}
        assert len(names) == len(set(names))
        by_name = {c['name']: c for c in body['commands']}
        if 'commands' in by_name:
            assert 'help' in by_name['commands']['aliases']
        assert not any(c['name'] == 'help' for c in body['commands'])
        assert body['total'] == len(body['commands'])

    run_test(bot, probe)


def test_spacy_fallback_loads_once_concurrently(tmp_path, monkeypatch):
    import time
    import jokes as j

    class FakeChunk:
        start_char = 0
        end_char = 3

    class FakeDoc:
        noun_chunks = [FakeChunk()]

    class FakeNlp:
        def __call__(self, text):
            return FakeDoc()

    calls = []

    def fake_load(name):
        calls.append(1)
        time.sleep(0.05)
        return FakeNlp()

    monkeypatch.setattr(j.spacy, 'load', fake_load)
    monkeypatch.setattr(j, '_nlp', None)
    monkeypatch.setattr(j, '_spacy_model', 'testmodel')

    async def main():
        a = asyncio.create_task(j.replace_random_noun_chunk('the walnuts are here', 'deez'))
        b = asyncio.create_task(j.replace_random_noun_chunk('some nouns around', 'deez'))
        return await asyncio.gather(a, b)

    out_a, out_b = asyncio.run(main())
    j._load_locks.clear()
    assert out_a == 'deez walnuts are here' and out_b == 'deeze nouns around'
    assert len(calls) == 1


def test_cmd_prefix_configured_and_default(tmp_path):
    custom = deezbot.DeezBot(
        cfg={'cmd_prefix': ['?'], 'scopes': [], 'channels': {'channel.chat.message': None}},
        storage=SQLiteStorage(os.path.join(str(tmp_path), 'twitch.db')),
    )
    assert custom.cmd_prefix == ['?']
    assert custom._prefix == ['?']

    default = make_bot(str(tmp_path))
    assert default.cmd_prefix == ['!', '~']
    assert default._prefix == ['!', '~']


def test_leave_gate_own_channel_only(tmp_path):
    bot = make_bot(str(tmp_path))
    sent = []

    async def fake_send(message, broadcaster_id=None):
        sent.append((message, broadcaster_id or 'OWN'))
        return [{'is_sent': True}]

    bot.http.sendChatMessage = fake_send
    bot.http.user_id = '8000001'

    user = {'user_id': '9000002', 'username': 'somechatter'}
    own_channel = {'broadcaster_id': '8000001', 'broadcaster_user_name': 'botchan'}
    foreign_channel = {'broadcaster_id': '7000003', 'broadcaster_user_name': 'otherchan'}

    async def main():
        await bot.storage.insert('channels', {'user_id': '9000002', 'jemote': 'GOTTEM'})
        await bot.cmd_leave(user, foreign_channel, [])
        assert sent == []
        rows = (await bot.storage.query('channels'))[0]
        assert str(rows['user_id']) == '9000002'
        bot.cmd_leave._rate_limit_state.clear()

        await bot.cmd_leave(user, own_channel, [])
        assert sent and all(broadcaster == '8000001' for _, broadcaster in sent)
        rows = [row for row in (await bot.storage.query('channels')) if str(row['user_id']) == '9000002']
        assert rows == []

    asyncio.run(main())


def test_ignore_any_channel_no_arg(tmp_path):
    bot = make_bot(str(tmp_path))
    sent = []

    async def fake_send(message, broadcaster_id=None):
        sent.append((message, broadcaster_id or 'OWN'))
        return [{'is_sent': True}]

    bot.http.sendChatMessage = fake_send

    user = {'user_id': '9000004', 'username': 'selfoptout'}
    foreign_channel = {'broadcaster_id': '7000005', 'broadcaster_user_name': 'otherchan'}

    async def main():
        await bot.cmd_ignore(user, foreign_channel, [])
        assert (await bot._get_ignore_status('9000004')) is True
        assert sent and all(broadcaster == '7000005' for _, broadcaster in sent)
        await bot.cmd_unignore(user, foreign_channel, [])
        assert (await bot._get_ignore_status('9000004')) is False

    asyncio.run(main())


def test_logs_endpoint(tmp_path):
    bot = make_bot(str(tmp_path))
    root = logging.getLogger()
    old_level = root.level
    root.setLevel(logging.DEBUG)
    try:
        logger.info('first probe line')
        logger.warning('second warning line')

        async def probe(client):
            r = await client.get('/api/logs?lines=10')
            assert r.status == 200
            body = await r.json()
            assert body['total'] >= 2
            msgs = [e['msg'] for e in body['entries']]
            assert 'first probe line' in msgs and 'second warning line' in msgs
            by_msg = {e['msg']: e for e in body['entries']}
            assert by_msg['second warning line']['level'] == 'WARNING'
            assert body['newest_seq'] >= body['oldest_seq']

            r = await client.get('/api/logs?lines=1')
            body = (await r.json())
            assert len(body['entries']) == 1

        run_test(bot, probe)
    finally:
        root.setLevel(old_level)


def test_makejoke_keyword_cooldown(tmp_path):
    bot = make_bot(str(tmp_path))
    bot.jdelay = (50, 60)
    bot.jcountmax = random.randint(*bot.jdelay)
    asyncio.run(bot.storage.insert('joke', {'keyword': 'fitness', 'joke': 'dick fit'}))

    async def probe():
        data1 = {'message': {'text': 'my fitness journey'}, 'broadcaster_user_id': '4000001'}
        r1 = await bot.makeJoke(data1)
        assert r1 is not None and 'dick fit' in r1
        assert bot.lastjoke > 0, 'keyword joke did not record lastjoke timestamp'
        data2 = {'message': {'text': 'my fitness journey'}, 'broadcaster_user_id': '4000001'}
        r2 = await bot.makeJoke(data2)
        assert r2 is None, f'keyword cooldown violated: {r2}'

    asyncio.run(probe())


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


def test_deez_loop_failure_logs_exception(tmp_path):
    bot = make_bot(str(tmp_path))
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    cap_logger = logging.getLogger('web_manage')
    handler = Capture()
    cap_logger.addHandler(handler)

    async def boom():
        raise RuntimeError('helix down for deezing')

    bot.check_connections = boom

    original_sleep = asyncio.sleep

    async def fast_sleep(seconds):
        await original_sleep(0.01)

    try:
        asyncio.sleep = fast_sleep

        async def main():
            task = asyncio.create_task(bot.deez_loop())
            while not records:
                await original_sleep(0.01)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(main())
    finally:
        asyncio.sleep = original_sleep
        cap_logger.removeHandler(handler)

    recs = [r for r in records if 'deez_loop Error' in r.getMessage()]
    assert recs, 'no deez_loop error record captured'
    msg = recs[0].getMessage()
    assert 'helix down for deezing' in msg
    assert '{e}' not in msg
    assert recs[0].exc_info is not None


def test_config_endpoint(tmp_path):
    bot = make_bot(str(tmp_path))

    async def probe(client):
        r = await client.get('/api/config')
        assert r.status == 200
        body = await r.json()
        assert body['status'] is True
        assert body['web_host'] == 'localhost'
        assert body['web_port'] == 5000
        assert body['jdelay'] == [1, 2]
        assert body['loop_delay'] == 3600
        assert body['default_jemote'] == 'Kappa'
        assert 'joke' in body['db_write_tables']
        assert body['log_buffer_size'] >= 1

    run_test(bot, probe)


def test_config_sections_from_yaml(tmp_path):
    bot = deezbot.DeezBot(cfg={
        'scopes': ['user:read:chat', 'user:write:chat'],
        'channels': {'channel.chat.message': None},
        'storage': SQLiteStorage(os.path.join(str(tmp_path), 'twitch.db')),
        'spacy_model': deezbot.DEFAULT_SPACY_MODEL,
        'jdelay': [7, 9],
        'jlimit': 321,
        'loop_delay': 61,
        'default_jemote': 'Peekaboo',
        'enrichment': {'channel_cache_ttl': 42},
        'web': {'host': '127.0.0.1', 'port': 5931, 'static_dirs': ['ui'], 'log_buffer_size': 55},
        'db_write_tables': ['joke'],
        'ui': {'status_poll_ms': 1234, 'log_poll_ms': 777},
    })

    assert bot.web_host == '127.0.0.1'
    assert bot.web_port == 5931
    assert bot.web_static_dirs == ['ui']
    assert deezbot._log_handler.buffer.maxlen == 55
    assert bot.jdelay == [7, 9]
    assert bot.jlimit == 321
    assert bot.loop_delay == 61
    assert bot.default_jemote == 'Peekaboo'
    assert bot.channel_cache_ttl == 42.0
    assert bot.db_write_tables == ('joke',)
    assert bot.ui_cfg['status_poll_ms'] == 1234
