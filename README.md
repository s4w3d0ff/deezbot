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

Creates a venv, installs dependencies (spacy, poolguy, aiosqlite, rich, click), and downloads the spaCy model.

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

## Structure

```
deezbot/
├── src/                  # Python source code
│   └── deez_nutz.py      # Bot logic (DeezBot + ChannelChatMessageAlert)
├── cfg.json              # Runtime configuration
├── db/                   # Runtime data (gitignored)
│   ├── jokes.json        # Keyword-to-joke mappings
│   ├── ignore.json       # Ignored user IDs
│   └── twitch.db         # OAuth tokens and channel state
├── .env                  # Twitch credentials (gitignored)
├── deez_venv/            # Virtual environment (gitignored)
├── install.sh / run.sh   # Linux setup/run scripts
├── install.bat / run.bat # Windows equivalents
└── requirements.txt      # Python dependencies
```

## Dependencies

- spacy (en_core_web_sm model)
- poolguy (Twitch bot framework)
- aiosqlite (async SQLite storage)
- rich (log formatting)
- click (CLI utilities from poolguy)

## Notes

- Bot ignores messages from itself, commands, and ignored users
- Joke cycle resets randomly after hitting jcountmax (between jdelay[0] and jdelay[1])
- Runtime cache files in db/ are recreated automatically if deleted
- Windows browser path in cfg.json is platform-specific, remove if not needed
