# deezbot

Twitch bot that tells "deez nutz" jokes in chat channels.

## Features

- Spontaneous jokes using spaCy noun-chunk replacement (replaces a random noun in user messages with "deez nutz")
- Keyword-triggered preset jokes (ligma, kansas, etc.)
- Multi-channel support via join/leave commands
- User ignore list to mute specific chatters
- Per-channel customizable emote for joke delivery
- Rate limiting on all commands (1 call per 15 seconds)

## Commands

| Command | Description | Permission |
|---------|-------------|------------|
| `/jemote <emote>` | Change channel emote used in jokes | Channel owner or bot itself |
| `/join` | Add this channel to bot's rotation | Bot's own channel |
| `/leave` | Remove this channel from rotation | Channel owner or bot itself |
| `/ignore <user>` | Mute a chatter permanently | Anyone |
| `/unignore <user>` | Unmute a previously ignored chatter | Anyone |
| `/help` | List available commands | Anyone |

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

Edit `cfg.json` for runtime settings:

```json
{
  "redirect_uri": "http://localhost:5000/callback",
  "scopes": ["user:read:chat", "user:write:chat"],
  "jdelay": [10, 20],        // random joke count between these values per cycle
  "jlimit": 600,              // seconds before keyword jokes reset
  "loop_delay": 300           // seconds between connection health checks
}
```

## Run

```bash
./run.sh
```

The bot starts, authenticates via Twitch OAuth (browser flow), subscribes to EventSub for channel chat messages, and begins processing. It auto-connects/disconnects from channels based on stream status.

## Web UI & API

While the bot runs it serves a local web control panel at `http://localhost:5000` — the same port as the OAuth callback (the server stays up in steady state now, instead of stopping after login).

The UI is a static dark single page (`ui/`, served at `/`) with four tabs:

- **Status** — bot account, uptime, token expiry countdown, websocket indicator, KPI counts (connected/live channels, ignored users, jokes) plus live joke state (cooldown window, seconds since last fire, remaining keyword cooldown, random counter vs next threshold), the bot's registered command list, the service log viewer, and the raw database browser. Status polls every 5 seconds; the log poll is a separate 2-second cycle while the tab is open.
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
| GET | `/api/logs?lines=200` | in-process log ring buffer (max 1000) tail, `oldest_seq`/`newest_seq` for incremental polling |
| POST | `/api/test/joke` | `{message}` → keyword/spacy dry run, no side effects |
| POST | `/api/test/chat` | `{message}` → real send to the bot's own channel, 400-char chunks |
| GET | `/api/db/tables` | table names, row counts, writable flag |
| GET | `/api/db/table/{table}?limit=200` | rows via storage query |
| POST | `/api/db/table/{table}` | upsert insert (whitelist: `joke`, `ignore`, `channels`) |
| DELETE | `/api/db/table/{table}` | delete by `where` + `params` (same whitelist) |

The server binds localhost only — no auth layer, do not expose the port. Writes to framework tables (`tokens`, `queue`, eventsub internals) return 403; reads stay open for all tables.

## Structure

```
deezbot/
├── src/                  # Python source code
│   └── deez_nutz.py      # Bot logic (DeezBot + ChannelChatMessageAlert)
├── test/                 # Offline API test suite (pytest, no network)
├── ui/                   # Static web control panel (served at /)
│   ├── index.html        # Single page shell
│   ├── app.js            # Tabs: status (+log, raw db), channels, ignore list, jokes
│   └── style.css         # Dark compact theme
├── cfg.json              # Runtime configuration
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
- Windows browser path in cfg.json is platform-specific, remove if not needed
