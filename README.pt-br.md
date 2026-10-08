**[Read in English](README.md)**

# Jarvis (nome provisório)

Assistente pessoal no espírito do J.A.R.V.I.S. do Tony Stark: conversa por voz fluida (dá pra interromper, com humor seco), proativo (lembretes, resumo do dia, avisos) e acessível por voz em casa e por Telegram em qualquer lugar. A memória de longo prazo mora num vault pessoal em Markdown; o trabalho pesado é delegado ao Claude Code.

> **Status: pré-alfa, fase de desenho.** Ainda sem código funcional. Sucessor de um projeto anterior (J.O.E.E), aproveitando só a orb, o resolvedor de projetos e o pipeline de treino de wake word.

## Arquitetura em um parágrafo

Dois cérebros. O **Falador** é um modelo rápido e barato por API (Claude Haiku por padrão; Gemini só pra teste) que carrega a persona e responde em tempo real. O **Trabalhador** é o Claude Code rodando em segundo plano pra tarefas de verdade. Um **núcleo** roteia entre os dois, conversa com o Telegram, agenda lembretes e escreve no inbox do vault. Um **cliente de voz** fino no Windows cuida de microfone, caixa de som e orb, ligado ao núcleo por WebSocket local. Detalhes em [docs/DESIGN.md](docs/DESIGN.md).

## Estrutura do repositório

| Caminho | O quê |
|---|---|
| `docs/DESIGN.md` | Desenho técnico e decisões |
| `prototype/` | Fase 0: protótipo de conversa por voz (plano e medições) |
| `persona/jarvis.md` | Prompt de sistema do Falador (persona, tom, regras de humor) |
| `config.example.env` | Nomes das configurações e segredos; copie pra `.env` (nunca vai pro git) |

## Configuração

Copie `config.example.env` pra `.env` e preencha. Segredos (chaves de API, token do bot do Telegram) ficam só no `.env`, que o git ignora.

## Licença

Ainda não escolhida.
