**[Read in English](README.md)**

# Jarvis (nome provisório)

Assistente pessoal no espírito do J.A.R.V.I.S. do Tony Stark: conversa por voz fluida (dá pra interromper, com humor seco), proativo (lembretes, resumo do dia, avisos) e acessível por voz em casa e por Telegram em qualquer lugar. A memória de longo prazo mora num vault pessoal em Markdown; o trabalho pesado é delegado ao Claude Code.

> **Status: pré-alfa.** A Fase 1 funciona: um bot de Telegram com persona de mordomo, humor com timing, notas no inbox do vault, acesso de leitura às tarefas pendentes, teto diário de gasto e uma cadeia de provedores de modelo. Ainda sem voz, e-mail, agenda nem controle do computador. Sucessor de um projeto anterior (J.O.E.E).

## Arquitetura em um parágrafo

Dois cérebros. O **Falador** é um modelo rápido e barato por API (hoje o `gpt-oss-120b` do Groq, com Gemini e Claude Haiku como provedores trocáveis ou reserva) que carrega a persona e responde em tempo real. O **Trabalhador** é o Claude Code rodando em segundo plano pra tarefas de verdade. Um **núcleo** roteia entre os dois, conversa com o Telegram, agenda lembretes e escreve no inbox do vault. Um **cliente de voz** fino no Windows cuida de microfone, caixa de som e orb, ligado ao núcleo por WebSocket local. Detalhes em [docs/DESIGN.md](docs/DESIGN.md).

## Início rápido

Precisa do [uv](https://docs.astral.sh/uv/) e de um token de bot do Telegram (pelo @BotFather).

```bash
uv sync
cp config.example.env .env      # depois preencha (nunca commite)
uv run python -m jarvis         # sobe o bot (long polling, sem porta aberta)
uv run python -m unittest discover -s tests
```

O bot só responde aos IDs do Telegram listados em `TELEGRAM_ALLOWED_USER_IDS`. Comandos: `/anota <texto>` (ou "anota ...") guarda uma nota no inbox do vault, `/tarefas [área]` lista as tarefas pendentes do vault (somente leitura), `/uso` mostra o uso e o custo de hoje, `/esquece` limpa a conversa.

## Estrutura do repositório

| Caminho | O quê |
|---|---|
| `docs/DESIGN.md` | Desenho técnico, decisões e estado da implementação |
| `src/jarvis/` | O bot: configuração, assistente, trava de humor, dicas de estilo, orçamento, acesso ao vault, provedores (`talker/`) |
| `tests/` | Testes unitários (`unittest` da biblioteca padrão) |
| `prototype/` | Fase 0: protótipo de conversa por voz (plano e medições) |
| `persona/jarvis.md` | Prompt de sistema do Falador (persona, tom, regras de humor) |
| `config.example.env` | Nomes das configurações e segredos; copie pra `.env` (nunca vai pro git) |

## Configuração

Copie `config.example.env` pra `.env` e preencha. Segredos (chaves de API, token do bot do Telegram) ficam só no `.env`, que o git ignora.

## Licença

Ainda não escolhida.
