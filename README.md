**[Leia em Português](README.pt-br.md)**

# Jarvis (working name)

A personal assistant in the spirit of Tony Stark's J.A.R.V.I.S.: fluid voice conversation (interruptible, with dry humor), proactive (reminders, daily digest, alerts), reachable by voice at home and by Telegram anywhere. Long-term memory lives in a personal Markdown vault; heavy work is delegated to Claude Code.

> **Status: pre-alpha, design phase.** No working code yet. Successor of an earlier project (J.O.E.E), reusing only its orb UI, project resolver and wake-word training pipeline.

## Architecture in one paragraph

Two brains. The **Talker** is a fast, cheap model behind an API (Claude Haiku by default; Gemini for testing only) that holds the persona and answers in real time. The **Worker** is Claude Code running headless in the background for real tasks. A **core** process routes between them, talks to Telegram, schedules reminders and writes to the vault's inbox. A thin **voice client** on Windows handles microphone, speakers and the orb, connected to the core over a local WebSocket. Details in [docs/DESIGN.md](docs/DESIGN.md).

## Repository layout

| Path | What |
|---|---|
| `docs/DESIGN.md` | Technical design and decisions |
| `prototype/` | Phase 0: voice-conversation prototype (plan and measurements) |
| `persona/jarvis.md` | System prompt for the Talker (persona, tone, humor rules) |
| `config.example.env` | Names of the settings and secrets; copy to `.env` (never committed) |

## Configuration

Copy `config.example.env` to `.env` and fill it in. Secrets (API keys, the Telegram bot token) live only in `.env`, which is git-ignored.

## License

Not chosen yet.
