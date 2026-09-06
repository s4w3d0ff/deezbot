# deezbot

Twitch bot that tells "deez nutz" jokes in chat channels.

## Features

- Spontaneous jokes using spaCy noun-chunk replacement (replaces a random noun in user messages with "deez nutz")
- Keyword-triggered preset jokes (ligma, kansas, etc.)
- Multi-channel support via join/leave commands (own channel only)
- Self joke opt-out: `!ignore` / `!unignore` stop or resume jokes for yourself, no argument needed
- Per-channel customizable emote for joke delivery
- Rate limiting on all commands (1 call per 15 seconds)

## Commands

Command prefixes come from the `cmd_prefix` key in `cfg.yaml` (default: `!`). Every command row below uses that prefix. No admin-style permissions exist; every command affects only the caller's own preferences.

| Command | Description | Permission |
|---------|-------------|------------|
| `!jemote <emote>` | Set your own emote used for joke delivery | Bot's own channel only |
| `!join` | Add yourself to the bot's rotation | Bot's own channel only |
| `!leave` | Remove yourself from the bot's rotation | Bot's own channel only |
| `!ignore` | Self opt-out: stop joke triggers for you, no user argument | Anyone, in any channel where the bot can see messages |
| `!unignore` | Self opt-in: re-enable joke triggers for you, no user argument | Anyone, in any channel where the bot can see messages |
| `!help` | List available commands (alias of `!commands`) | Anyone |

## Setup

```bash
chmod +x install.sh run.sh
./install.sh
```

Creates a venv, installs dependencies (spacy, poolguy, aiosqlite, rich, pytest), and downloads the spaCy model.

## Configuration

Create `.env` in the project root with:

```
DEEZ_CLIENT_ID=your-twitch-client-id
DEEZ_CLIENT_SECRET=your-twitch-client-secret
```

Edit `cfg.yaml` for runtime settings (values below match the shipped file):

```yaml
scopes: [user:read:chat, user:write:chat]
channels: {channel.chat.message: null}
storage: sqlite
browser: firefox          # browser opened for the Twitch OAuth page (omit for system default)

jdelay: [10, 20]          # random-joke count window per cycle (min, max)
jlimit: 600               # seconds between keyword jokes (cooldown window)
loop_delay: 300           # seconds between connection health checks
default_jemote: Kappa     # jemote used when a channel has none stored
cmd_prefix: ['!', '~']    # chat command prefixes loaded at bot start (one character per entry)

web:
  host: localhost         # control panel + OAuth callback bind host
  port: 5000              # control panel + OAuth callback port (bind derives from these)
  static_dirs: [ui]       # directories served at /<dir>/... by the web server
  log_buffer_size: 1000   # in-process service log ring buffer capacity (lines)

enrichment:
  channel_cache_ttl: 60   # seconds to cache users/streams enrichment for channels + status

spacy_model: en_core_web_sm

db_write_tables: [joke, ignore, channels]   # tables writable via /api/db/table (rest read-only)

ui:
  status_poll_ms: 5000    # how often the Status tab polls /api/status
  log_poll_ms: 2000       # how often the Service Log fetches new lines
  page_size: 200          # rows per table view in the DB browser
  joke_list_limit: 500    # max keywords loaded into the Jokes editor
```

Credentials stay out of `cfg.yaml` — they come from `.env`. The effective config is exposed at `/api/config`, which the UI reads to drive its poll intervals and page limits.

## Run

```bash
./run.sh
```

The bot starts, authenticates via Twitch OAuth (browser flow), subscribes to EventSub for channel chat messages, and begins processing. It auto-connects/disconnects from channels based on stream status.

## Web UI & API

While the bot runs it serves a local web control panel at `http://localhost:5000` — the same port as the OAuth callback (the server stays up in steady state now, instead of stopping after login).

The UI is a static dark single page (`ui/`, served at `/`) with four tabs:

- **Status** — bot account, uptime, token expiry countdown, websocket indicator, KPI counts (connected/live channels, ignored users, jokes) plus live joke state (cooldown window, seconds since last fire, remaining keyword cooldown, random counter vs next threshold), the bot's registered command list, the service log viewer, and the raw database browser. Poll cycles are config-driven (`ui.status_poll_ms`, `ui.log_poll_ms` in `cfg.yaml`; the log cycle only runs while the tab is open).
- **Channels** — connected channels with live dot, viewers and stream title per channel (enriched via the Twitch users/streams APIs, 60s cache), inline jemote editing, remove button, and an add form that resolves a twitch username to its user id before writing the row.
- **Ignore List** — ignored users enriched with login/display name; unignore toggles the flag back off without deleting history, remove deletes the row; add form resolves a twitch username the same way as Channels (writes `ignore=1`, matching the chat command).
- **Jokes** — joke dry-run and own-channel test chat on top of the keyword editor with inline edit/add/delete. Live joke-state KPIs are shown on the Status tab so they stay visible while watching logs.

JSON endpoints behind the UI:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/status` | bot account/username, uptime, token expiry, ws session, connected/live channel counts, ignore/joke totals, live joke state (cooldown + counters) |
| GET | `/api/channels` | per-channel detail enriched with login, display name, live state, viewers, stream title (60s cache) |
| POST | `/api/channels` | `{login, jemote?}` → resolve user via users API and add channel row; 404 on unknown user |
| GET | `/api/ignores` | ignore list rows enriched with user login/display name and effective `ignored` flag |
| POST | `/api/ignores` | `{login}` → resolve user and set `ignore=1`; 404 on unknown user |
| GET | `/api/commands` | registered bot commands with aliases and help text |
| GET | `/api/config` | effective runtime config: web bind, joke timing, cache ttl, writable tables, log buffer size, ui section |
| GET | `/api/logs?lines=200` | in-process log ring buffer (max 1000) tail, `oldest_seq`/`newest_seq` for incremental polling |
| POST | `/api/test/joke` | `{message}` → keyword/spacy dry run, no side effects |
| POST | `/api/test/chat` | `{message}` → real send to the bot's own channel, 400-char chunks |
| GET | `/api/db/tables` | table names, row counts, writable flag |
| GET | `/api/db/table/{table}?limit=200` | rows via storage query |
| POST | `/api/db/table/{table}` | upsert insert (whitelist: `joke`, `ignore`, `channels`) |
| DELETE | `/api/db/table/{table}` | delete by `where` + `params` (same whitelist) |

The server binds localhost only. No auth layer, do not expose the port. Framework secret tables (`tokens`, `queue`) are excluded from both the table listing and direct reads (403); all other tables remain readable in the raw DB browser.

## Structure

```
deezbot/
├── src/                  # Python source code
│   ├── bot.py            # DeezBot hub: mixin composition, joke state, storage helpers
│   ├── alerts.py         # ChannelChatMessageAlert (chat message handler)
│   ├── commands.py       # CommandsMixin (jemote/join/leave/ignore/unignore)
│   ├── config.py         # YAML loader + default writable tables
│   ├── jokes.py          # spacy noun-chunk joke engine
│   ├── logbuffer.py      # ring-buffer logging handler for the service log viewer
│   ├── web_api.py        # WebApiMixin (status/channels/ignores/test routes)
│   ├── web_db.py         # WebDbMixin (raw database editor routes)
│   └── web_manage.py     # WebManageMixin (log/config endpoints, service loop)
├── test/                 # Offline API test suite (pytest, no network)
├── ui/                   # Static web control panel (served at /)
│   ├── index.html        # Single page shell
│   ├── app.js            # Tab switching + boot
│   ├── js/api.js         # Shared helpers: dom, toast, api calls, config, formatters
│   ├── js/status.js      # Status tab: KPIs, joke state, commands, log viewer
│   ├── js/channels.js    # Channels tab
│   ├── js/ignores.js     # Ignore list tab
│   ├── js/jokes.js       # Jokes tab (dry-run, test chat, keyword editor)
│   ├── js/rawdb.js       # Raw database browser
│   └── style.css         # Dark compact theme
├── cfg.yaml              # Runtime configuration (YAML)
├── db/                   # Runtime data (gitignored)
│   └── twitch.db         # SQLite storage (tokens, jokes, channels, ignores)
├── .env                  # Twitch credentials (gitignored)
├── deez_venv/            # Virtual environment (gitignored)
├── install.sh / run.sh   # Linux setup/run scripts
├── install.bat / run.bat # Windows equivalents
└── requirements.txt      # Python dependencies
```

## Dependencies

- spacy (en_core_web_sm model)
- poolguy (Twitch bot framework, pinned to dev branch)
- aiosqlite (async SQLite storage)
- rich (log formatting)

## Notes

- Bot ignores messages from itself, commands, and ignored users
- Joke cycle resets randomly after hitting jcountmax (between jdelay[0] and jdelay[1])
- Runtime cache files in db/ are recreated automatically if deleted
- `browser` in cfg.yaml is platform-specific (e.g. firefox); omit it for the system default browser
