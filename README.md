**[Leia em Português](README.pt-br.md)**

# Jarvis (working name)

A personal assistant in the spirit of Tony Stark's J.A.R.V.I.S.: fluid voice conversation (interruptible, with dry humor), proactive (reminders, daily digest, alerts), reachable by voice at home and by Telegram anywhere. Long-term memory lives in a personal Markdown vault; heavy work is delegated to Claude Code.

> **Status: pre-alpha.** Phase 1 works: a Telegram bot with a butler persona, timed humor, notes into the vault inbox, read-only access to the pending tasks, a daily spending cap and a chain of model providers. No voice, e-mail, calendar or computer control yet. Successor of an earlier project (J.O.E.E).

## Architecture in one paragraph

Two brains. The **Talker** is a fast, cheap model behind an API (today Groq's `gpt-oss-120b`, with Gemini and Claude Haiku as swappable or fallback providers) that holds the persona and answers in real time. The **Worker** is Claude Code running headless in the background for real tasks. A **core** process routes between them, talks to Telegram, schedules reminders and writes to the vault's inbox. A thin **voice client** on Windows handles microphone, speakers and the orb, connected to the core over a local WebSocket. Details in [docs/DESIGN.md](docs/DESIGN.md).

## Quick start

Needs [uv](https://docs.astral.sh/uv/) and a Telegram bot token (from @BotFather).

```bash
uv sync
cp config.example.env .env      # then fill it in (never commit it)
uv run python -m jarvis         # starts the bot (long polling, no open port)
uv run python -m unittest discover -s tests
```

The bot only answers the Telegram user ids listed in `TELEGRAM_ALLOWED_USER_IDS`. Commands: `/anota <text>` (or "anota ...") saves a note into the vault inbox, `/tarefas [area]` lists pending tasks from the vault (read-only), `/uso` shows today's usage and cost, `/esquece` clears the conversation.

## Repository layout

| Path | What |
|---|---|
| `docs/DESIGN.md` | Technical design, decisions and implementation status |
| `src/jarvis/` | The bot: config, assistant, humor gate, style hints, budget, vault access, providers (`talker/`) |
| `tests/` | Unit tests (stdlib `unittest`) |
| `prototype/` | Phase 0: voice-conversation prototype (plan and measurements) |
| `persona/jarvis.md` | System prompt for the Talker (persona, tone, humor rules) |
| `config.example.env` | Names of the settings and secrets; copy to `.env` (never committed) |

## Configuration

Copy `config.example.env` to `.env` and fill it in. Secrets (API keys, the Telegram bot token) live only in `.env`, which is git-ignored.

## License

Not chosen yet.
