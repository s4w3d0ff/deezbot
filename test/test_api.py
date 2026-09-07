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


def test_joke_schema_fresh_db_auto_creates(tmp_path):
    bot = make_bot(str(tmp_path))
    recs = []

    class Capture(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.CRITICAL:
                recs.append(record)

    cap_logger = logging.getLogger('bot')
    handler = Capture()
    cap_logger.addHandler(handler)
    try:
        asyncio.run(bot._check_joke_schema())
        jokes = asyncio.run(bot._get_jokes())
    finally:
        cap_logger.removeHandler(handler)

    assert recs == [], f"fresh db must not log schema drift, got {[r.getMessage() for r in recs]}"
    assert jokes == {}


def test_joke_schema_drift_logs_critical_and_dry_run_errors(tmp_path):
    bot = make_bot(str(tmp_path))
    asyncio.run(bot.storage.insert('joke', {'word': 'fitness', 'text': 'dick fit'}))

    recs = []

    class Capture(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.CRITICAL:
                recs.append(record)

    cap_logger = logging.getLogger('bot')
    handler = Capture()
    cap_logger.addHandler(handler)
    try:
        asyncio.run(bot._check_joke_schema())

        async def probe(client):
            r = await client.post('/api/test/joke', json={'message': 'my fitness journey'})
            assert r.status >= 500, f"drifted schema dry run must be an error response, got {r.status}"

        run_test(bot, probe)
    finally:
        cap_logger.removeHandler(handler)

    crit = [r for r in recs if 'schema drift' in r.getMessage()]
    assert len(crit) == 1, f"drifted schema must log exactly one CRITICAL, got {len(crit)}"
    msg = crit[0].getMessage()
    assert 'word' in msg and 'text' in msg, f"CRITICAL must name the actual columns found: {msg}"


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


def test_status_survives_ws_internal_renames(tmp_path):
    bot = make_bot(str(tmp_path))
    bot.ws = object()

    async def probe(client):
        r = await client.get('/api/status')
        assert r.status == 200, f"status must survive ws internal renames, got {r.status}"
        body = await r.json()
        assert body['ws_connected'] is False, 'missing socket/session attrs must degrade to False'

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


def test_malformed_bodies_return_json_400(tmp_path):
    bot = make_bot(str(tmp_path))

    async def probe(client):
        r = await client.post('/api/channels', data='not json at all', headers={'Content-Type': 'text/plain'})
        assert r.status == 400, f"non-JSON channel body must be a JSON 400, got {r.status}"
        body = await r.json()
        assert body['status'] is False and 'error' in body

        r = await client.post('/api/db/table/joke', data='', headers={'Content-Type': 'text/plain'})
        assert r.status == 400, f"empty db insert body must be a JSON 400, got {r.status}"
        body = await r.json()
        assert body['status'] is False and 'error' in body

    run_test(bot, probe)


def test_channels_add_upstream_failure_502(tmp_path):
    bot = make_bot(str(tmp_path))

    async def boom(logins=None, **kwargs):
        raise RuntimeError('helix exploded')

    bot.http.getUsers = boom

    async def probe(client):
        r = await client.post('/api/channels', json={'login': 'somechan'})
        assert r.status == 502, f"upstream lookup failure must be a JSON 502, got {r.status}"
        body = await r.json()
        assert body['status'] is False and 'twitch user lookup failed' in body['error']

    run_test(bot, probe)
    rows = asyncio.run(bot.storage.query('channels'))
    assert rows == [], 'failed channel add must not write a storage row'


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

            r = await client.get('/api/logs?lines=xyz')
            assert r.status == 400, f"garbage lines param must be a JSON 400, got {r.status}"
            body = (await r.json())
            assert body['status'] is False and 'invalid' in body['error']

            r = await client.get('/api/logs?lines=1')
            body = (await r.json())
            assert len(body['entries']) == 1

        run_test(bot, probe)
    finally:
        root.setLevel(old_level)


def test_makejoke_keyword_cooldown(tmp_path):
    bot = make_bot(str(tmp_path))
    bot.jdelay = (50, 60)
    bot.next_joke_after = random.randint(*bot.jdelay)
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
        before = (bot.msg_since_joke, bot.lastjoke)
        r = await client.post('/api/test/joke', json={'message': '1 2 3'})
        assert r.status == 200
        body = await r.json()
        assert body['reply'] is None
        assert (bot.msg_since_joke, bot.lastjoke) == before

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
        assert 'joke' in tables
        assert 'tokens' not in tables, 'token rows must not be listed in the raw DB browser'
        assert tables['joke']['writable'] is True
        assert tables['joke']['row_count'] == 1

        r = await client.get('/api/db/table/joke?limit=abc')
        assert r.status == 400, f"non-numeric limit must be a JSON 400, got {r.status}"
        body = await r.json()
        assert body['status'] is False and 'invalid' in body['error']

        rows = (await (await client.get('/api/db/table/joke?limit=1')).json())['rows']
        assert len(rows) == 1, 'numeric limit slicing must keep working'

        rows = (await (await client.get('/api/db/table/joke?limit=-5')).json())['rows']
        assert rows == [], 'negative limit slices to empty (pre-existing behavior)'

    run_test(bot, probe)


def test_db_delete_shape_validation(tmp_path):
    bot = make_bot(str(tmp_path))
    asyncio.run(bot.storage.insert('joke', {'keyword': 'victim', 'joke': 'should survive bad deletes'}))

    async def probe(client):
        r = await client.delete('/api/db/table/joke', json={'where': 'keyword = ?', 'params': 'abc'})
        assert r.status == 400, f"old-style where/params body must be a JSON 400, got {r.status}"
        body = await r.json()
        assert body['status'] is False and 'primary-key' in body['error']

        rows = (await (await client.get('/api/db/table/joke')).json())['rows']
        assert [row for row in rows if row['keyword'] == 'victim'], 'failed delete must not touch storage'

        r = await client.delete('/api/db/table/joke', json={'where': '1=1', 'params': []})
        assert r.status == 400, f"mass-delete body must be a JSON 400, got {r.status}"
        rows = (await (await client.get('/api/db/table/joke')).json())['rows']
        assert len(rows) == 1 and rows[0]['keyword'] == 'victim', 'old-style mass delete must leave every row intact'

    run_test(bot, probe)


def test_db_delete_injection_replays(tmp_path):
    bot = make_bot(str(tmp_path))
    asyncio.run(bot.storage.insert('joke', {'keyword': 'alpha', 'joke': 'one'}))
    asyncio.run(bot.storage.insert('joke', {'keyword': 'beta', 'joke': 'two'}))
    asyncio.run(bot.storage.save_token('twitch', {'token_json': '{"access_token": "leaked-material"}'}))

    async def tokens_row():
        rows = await bot.storage.query('tokens')
        return [row for row in rows if row.get('name') == 'twitch']

    before = asyncio.run(tokens_row())
    assert len(before) == 1, 'test needs exactly one seeded tokens row'

    async def probe(client):
        r = await client.delete('/api/db/table/joke', json={'where': '1=1 AND EXISTS (SELECT 1 FROM tokens WHERE token_json LIKE ?)', 'params': ['%leaked-material%']})
        assert r.status == 400, f"subquery oracle body must be a JSON 400, got {r.status}"

        r = await client.delete('/api/db/table/tokens', json={'name': 'twitch'})
        assert r.status == 403, 'protected table delete must stay 403 even with the structured body'

    run_test(bot, probe)

    after = asyncio.run(tokens_row())
    assert after == before, 'tokens row must be byte-identical after failed oracle deletes'
    rows = asyncio.run(bot.storage.query('joke'))
    assert len(rows) == 2, 'both joke rows must survive the injection replays'


def test_db_delete_single_pk_each_writable_table(tmp_path):
    bot = make_bot(str(tmp_path))

    async def probe(client):
        r = await client.post('/api/db/table/joke', json={'keyword': 'tulip', 'joke': 'deez nutz on yo head'})
        assert r.status == 200
        r = await client.post('/api/db/table/ignore', json={'user_id': '5500001', 'ignore': 'True'})
        assert r.status == 200
        r = await client.post('/api/db/table/channels', json={'user_id': '5500002', 'jemote': 'Kappa'})
        assert r.status == 200

        for table, pk in (('joke', {'keyword': 'tulip'}), ('ignore', {'user_id': '5500001'}), ('channels', {'user_id': '5500002'})):
            r = await client.delete(f'/api/db/table/{table}', json=pk)
            assert r.status == 200, f"structured single-PK delete on {table} must succeed, got {r.status}"

        for table in ('joke', 'ignore', 'channels'):
            rows = (await (await client.get(f'/api/db/table/{table}')).json())['rows']
            assert rows == [], f'{table} must be empty after single-row deletes'

    run_test(bot, probe)


def test_db_delete_rejects_wrong_pk_and_shapes(tmp_path):
    bot = make_bot(str(tmp_path))
    asyncio.run(bot.storage.insert('joke', {'keyword': 'keeper', 'joke': 'stays'}))

    async def probe(client):
        r = await client.delete('/api/db/table/joke', json={'joke': 'stays'})
        assert r.status == 400, f"non-PK column body must be a JSON 400, got {r.status}"
        body = await r.json()
        assert 'keyword' in body['error']

        for bad_body in ({}, {'keyword': 'keeper', 'joke': 'stays'}, {'keyword': 5}):
            r = await client.delete('/api/db/table/joke', json=bad_body)
            assert r.status == 400, f"body {bad_body!r} must be a JSON 400, got {r.status}"

        rows = (await (await client.get('/api/db/table/joke')).json())['rows']
        assert len(rows) == 1 and rows[0]['keyword'] == 'keeper', 'rejected shapes must not delete the row'

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

        r = await client.delete('/api/db/table/joke', json={'keyword': 'tulip'})
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
        assert r.status == 403
        body = await r.json()
        assert body['status'] is False and 'error' in body

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


def test_chat_cap_2001_chars_rejected_zero_sends(tmp_path):
    bot = make_bot(str(tmp_path))
    sent = []

    async def fake_send(message, broadcaster_id=None):
        sent.append((message, broadcaster_id or 'OWN'))
        return [{'is_sent': True}]

    bot.http.sendChatMessage = fake_send

    async def probe(client):
        r = await client.post('/api/test/chat', json={'message': 'a' * 2001})
        assert r.status == 400, f"2001 char body must be a JSON 400, got {r.status}"
        body = await r.json()
        assert body['status'] is False and 'character limit' in body['error']

    run_test(bot, probe)
    assert sent == [], 'over-cap message must not fire any sendChatMessage call'


def test_chat_1500_chars_sends_and_reports_chunks(tmp_path):
    bot = make_bot(str(tmp_path))
    chunks = []

    async def fake_send(message, broadcaster_id=None):
        chunks.append(message)
        return [{'is_sent': True}]

    bot.http.sendChatMessage = fake_send

    message = ' '.join(['word%d' % i for i in range(201)])
    assert len(message) == 1497, f"test fixture must stay just under the cap: {len(message)}"

    async def probe(client):
        r = await client.post('/api/test/chat', json={'message': message})
        assert r.status == 200
        body = await r.json()
        assert body['sent_chunks'] == 4, f"1497 char message must send in four 400-char chunks, got {body['sent_chunks']}"

    run_test(bot, probe)
    assert len(chunks) == 4 and all(len(c) <= 400 for c in chunks)


def test_preauth_joke_falls_back_to_default_jemote(tmp_path):
    bot = make_bot(str(tmp_path))
    asyncio.run(bot.storage.insert('joke', {'keyword': 'fitness', 'joke': 'dick fit'}))
    bot.http.user_id = None

    async def probe(client):
        r = await client.post('/api/test/joke', json={'message': 'my fitness journey'})
        assert r.status == 200, f"pre-auth keyword dry run must not error, got {r.status}"
        body = await r.json()
        assert body['matched_keyword'] == 'fitness'
        assert body['reply'].endswith(bot.default_jemote)

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


def test_check_connections_connects_own_channel_when_unsubscribed(tmp_path):
    bot = make_bot(str(tmp_path))
    asyncio.run(bot.storage.insert('channels', {'user_id': '1000001', 'jemote': 'Kappa'}))
    bot.http.user_id = '1000001'

    async def fake_get_event_subs(status=None):
        return {'data': []}

    async def fake_get_streams(user_id=None, **kwargs):
        return []

    created = []

    class FakeWs:
        async def create_event_sub(self, event_type, user_id):
            created.append((event_type, str(user_id)))

    deleted = []

    async def fake_delete(eventsub_id):
        deleted.append(str(eventsub_id))
        return {'id': eventsub_id}

    bot.http.getEventSubs = fake_get_event_subs
    bot.http.getStreams = fake_get_streams
    bot.http.deleteEventSub = fake_delete
    bot.ws = FakeWs()

    asyncio.run(bot.check_connections())

    assert created == [('channel.chat.message', '1000001')]
    assert deleted == []


def test_check_connections_disconnects_stale_eventsub_and_logs_failure(tmp_path):
    bot = make_bot(str(tmp_path))
    bot.http.user_id = '9000009'

    stale = {'id': 'evt_9', 'condition': {'broadcaster_user_id': 3000001}}

    async def fake_get_event_subs(status=None):
        assert status == 'enabled'
        return {'data': [stale]}

    deleted = []

    async def fake_delete(eventsub_id):
        deleted.append(str(eventsub_id))
        return None

    class FakeWs:
        async def create_event_sub(self, event_type, user_id):
            pass

    bot.http.getEventSubs = fake_get_event_subs
    bot.http.deleteEventSub = fake_delete
    bot.ws = FakeWs()

    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    cap_logger = logging.getLogger('bot')
    handler = Capture()
    cap_logger.addHandler(handler)
    try:
        asyncio.run(bot.check_connections())
    finally:
        cap_logger.removeHandler(handler)

    assert deleted == ['evt_9']
    errs = [r for r in records if "Couldn't disconnect" in r.getMessage()]
    assert errs, 'falsy deleteEventSub result must log the Could not disconnect error path'


def test_connected_channels_coerces_eventsub_keys_to_strings(tmp_path):
    bot = make_bot(str(tmp_path))

    async def fake_get_event_subs(status=None):
        return {'data': [{'id': 'evt_1', 'condition': {'broadcaster_user_id': 2000003}}]}

    bot.http.getEventSubs = fake_get_event_subs

    out = asyncio.run(bot.connected_channels())

    assert set(out.keys()) == {'2000003'}, 'int broadcaster_user_id must be coerced to a string key'
    assert out['2000003'] == {'id': 'evt_1', 'condition': {'broadcaster_user_id': 2000003}}


def test_enrich_channels_live_map_keys_by_stream_user_id(tmp_path):
    bot = make_bot(str(tmp_path))
    asyncio.run(bot.storage.insert('channels', {'user_id': '5000001', 'jemote': 'Kappa'}))

    async def fake_get_users(ids=None, logins=None):
        return []

    async def fake_get_streams(user_id=None, **kwargs):
        assert user_id == ['5000001']
        return [{'id': 'STREAM_ID', 'user_id': '5000001', 'viewer_count': 7, 'title': 't'}]

    bot.http.getUsers = fake_get_users
    bot.http.getStreams = fake_get_streams

    out = asyncio.run(bot._enrich_channels())

    entry = out['5000001']
    assert entry['is_live'] is True, 'live stream row must key the live map by user_id, not stream id'
    assert entry['viewers'] == 7
    assert entry['title'] == 't'


def test_origin_guard_cross_and_same_origin(tmp_path):
    bot = make_bot(str(tmp_path))

    async def probe(client):
        evil_headers = {'Origin': 'http://evil.example', 'Content-Type': 'text/plain'}
        r = await client.post('/api/db/table/joke', data='{"keyword": "evil", "joke": "nope"}', headers=evil_headers)
        assert r.status == 403
        body = await r.json()
        assert body['status'] is False and 'error' in body
        rows = (await (await client.get('/api/db/table/joke')).json())['rows']
        assert not [row for row in rows if row['keyword'] == 'evil'], 'cross-origin write must not reach storage'

        r = await client.delete('/api/db/table/joke', data='{"where": "1=1"}', headers={'Origin': 'http://evil.example'})
        assert r.status == 403, 'state changing DELETE with foreign Origin must be rejected'

        origin = f"http://{client.host}:{client.port}"
        r = await client.post('/api/db/table/joke', json={'keyword': 'friendly', 'joke': 'same origin ok'}, headers={'Origin': origin})
        assert r.status == 200, 'same-origin request must not be blocked'
        rows = (await (await client.get('/api/db/table/joke')).json())['rows']
        assert [row for row in rows if row['keyword'] == 'friendly'], 'same-origin insert should land'

    run_test(bot, probe)


def test_nonloopback_bind_warns(tmp_path):
    cap_logger = logging.getLogger('bot')
    recs = []

    class Capture(logging.Handler):
        def emit(self, record):
            if 'reachable beyond this machine' in record.getMessage():
                recs.append(record)

    handler = Capture()
    cap_logger.addHandler(handler)
    try:
        make_bot(str(tmp_path))
        assert recs == [], 'localhost bind must not trigger the exposure warning'

        exposed = deezbot.DeezBot(cfg={
            'scopes': [], 'channels': {'channel.chat.message': None},
            'storage': SQLiteStorage(os.path.join(str(tmp_path), 'exposed.db')),
            'web': {'host': '192.168.0.50', 'port': 5000},
        })
    finally:
        cap_logger.removeHandler(handler)

    assert exposed.web_host == '192.168.0.50'
    assert len(recs) == 1, 'non-loopback bind must log exactly one warning at construction'


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


def test_log_buffer_caps_entry_and_quiet_repeat_connection_dump(tmp_path):
    bot = make_bot(str(tmp_path))
    assert deezbot._log_handler.buffer.maxlen == 1000

    recs = []

    class Capture(logging.Handler):
        def emit(self, record):
            recs.append(record)

    cap_logger = logging.getLogger('deeztest')
    handler = Capture()
    cap_logger.addHandler(handler)
    try:
        deezbot._log_handler.buffer.clear()
        for i in range(999):
            cap_logger.warning(f'filler {i}')
        cap_logger.warning('H' * 5000)
        entries = list(deezbot._log_handler.buffer)
        assert len(entries) == 1000, f"buffer must stay bounded at maxlen, got {len(entries)}"
        assert all(len(e['msg']) <= 500 for e in entries), 'every stored entry msg must be capped at 500 chars'
        huge = [e for e in entries if e['msg'].startswith('H')]
        assert len(huge) == 1 and len(huge[0]['msg']) == 500, f'huge line must truncate to exactly 500, got {len(huge[0]["msg"])}'

        bot.http.user_id = '8000200'
        warn_msgs = []

        class WarnCap(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.WARNING:
                    warn_msgs.append(record.getMessage())

        async def fake_eventsubs():
            return {'8000200': {'id': 'ev1'}}

        async def no_channels():
            return {}

        bot.connected_channels = fake_eventsubs
        bot._get_channel_list = no_channels
        warn_logger = logging.getLogger('bot')
        whandler = WarnCap()
        warn_logger.addHandler(whandler)
        try:
            async def main():
                await bot.check_connections()
                await bot.check_connections()
                await bot.check_connections()
            asyncio.run(main())
        finally:
            warn_logger.removeHandler(whandler)

        conn_dumps = [m for m in warn_msgs if 'Current connections' in m]
        assert len(conn_dumps) == 1, f"unchanged connection set must log the dump exactly once across cycles, got {len(conn_dumps)}"
        assert "'8000200'" in conn_dumps[0], f'dump must name the connected ids: {conn_dumps[0]}'
    finally:
        cap_logger.removeHandler(handler)


def test_jemote_arg_validation_no_onair_errors(tmp_path):
    bot = make_bot(str(tmp_path))
    sent = []

    async def fake_send(message, broadcaster_id=None):
        sent.append((message, broadcaster_id or 'OWN'))
        return [{'is_sent': True}]

    bot.http.sendChatMessage = fake_send
    bot.http.user_id = '8000100'
    bot.cmd_jemote._rate_limit_state.clear()

    own_channel = {'broadcaster_id': '8000100', 'broadcaster_user_name': 'botchan'}
    users = {
        'noargs': {'user_id': '9000101', 'username': 'nobody'},
        'overlong': {'user_id': '9000102', 'username': 'toolong'},
        'withspace': {'user_id': '9000103', 'username': 'hasgap'},
        'valid': {'user_id': '9000104', 'username': 'goodone'},
    }

    errors = []

    class Capture(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.ERROR:
                errors.append(record)

    cap_logger = logging.getLogger('commands')
    handler = Capture()
    cap_logger.addHandler(handler)
    try:
        async def main():
            await bot.cmd_jemote(users['noargs'], own_channel, [])
            await bot.cmd_jemote(users['overlong'], own_channel, ['x' * 33])
            await bot.cmd_jemote(users['withspace'], own_channel, ['two words'])
            assert sent == [], 'rejected shapes must not send any chat message or raise'

            await bot.cmd_jemote(users['valid'], own_channel, ['GOTTEM'])
        asyncio.run(main())
    finally:
        cap_logger.removeHandler(handler)

    assert errors == [], f"jemote dispatches must not log exceptions, got {[r.getMessage() for r in errors]}"
    assert sent and 'GOTTEM I like it' in sent[0][0], f'valid emote must still be acked: {sent}'
    rows = [row for row in (asyncio.run(bot.storage.query('channels'))) if str(row['user_id']) == '9000104']
    assert len(rows) == 1 and rows[0]['jemote'] == 'GOTTEM'
    rejected_ids = {'9000101', '9000102', '9000103'}
    all_rows = asyncio.run(bot.storage.query('channels'))
    assert not any(str(row['user_id']) in rejected_ids for row in all_rows), 'rejected shapes must not store a channel row'
