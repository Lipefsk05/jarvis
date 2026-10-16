# Jarvis — desenho técnico

Documento vivo do desenho. Estado: **Fase 1 implementada e rodando** (ver "Estado da implementação"); voz e demais fases ainda só em desenho. Atualizar quando uma decisão mudar.

## Objetivo

Assistente pessoal com conversa por voz fluida (interrupção, humor seco com timing), proativo (lembretes, resumo do dia, avisos), acessível por voz em casa e por Telegram fora. Memória de longo prazo num vault pessoal em Markdown; trabalho pesado delegado ao Claude Code. Meta de custo: o mais próximo de zero que der.

## Componentes

```text
 Telegram (fora)            Microfone + fone/caixa (em casa)
      |                                |
      |                       [Cliente de voz - Windows]
      |                       wake word + VAD + STT, TTS, orb
      |                                | WebSocket local
      v                                v
 +------------------------------ NÚCLEO (WSL) ----------------------------+
 |  bot Telegram | agendador | roteador | caixa de saída                    |
 |  FALADOR (API): persona, humor, resposta imediata                        |
 |       | "isso é trabalho" -> fila                                        |
 |  TRABALHADOR: claude -p (sessão por tarefa), segundo plano               |
 |  VAULT: lê índice/estado | escreve só em inbox/jarvis/ | log              |
 +--------------------------------------------------------------------------+
```

- **Falador**: modelo rápido por API atrás de uma interface de provedor trocável, com uma **cadeia** (`JARVIS_TALKER_PROVIDER` e `JARVIS_TALKER_FALLBACK_PROVIDERS`). Hoje o principal é o Groq (`gpt-oss-120b`, raciocínio mínimo); `gemini` é reserva possível (o plano grátis pode usar o conteúdo enviado); `anthropic` (Haiku) entra se o dono quiser pagar. Cada provedor tem os próprios modelos e preços. Recebe persona + estado atual + últimos turnos + flag `humor_permitido`.
- **Trabalhador**: Claude Code headless (`claude -p`, `--resume` só dentro da mesma tarefa). Roda em segundo plano; o Falador avisa quando termina.
- **Cliente de voz**: Python no Windows (áudio nativo). Só captura/toca áudio e desenha a orb; a lógica fica no núcleo.
- **Núcleo**: Python no WSL, ao lado do Claude Code e do vault. Canal é um **adaptador** (Telegram hoje; app próprio depois).

## Voz

- Framework pronto (Pipecat ou LiveKit Agents) para VAD, turnos e interrupção, em vez de loop escrito à mão.
- STT: faster-whisper (GPU). TTS: Kokoro `pf_dora` vs Piper, a comparar ouvindo.
- **Wake word sem espera**: buffer circular de áudio só em memória (pre-roll); ao detectar o nome, o trecho antes e depois entra na transcrição. Verificação local de contexto (chamou vs só mencionou). Modo conversa depois de ativado. O detector não gasta token.
- Cancelamento de eco: fone no começo; caixa de som exige AEC.

## Persona e humor

Prompt em `persona/jarvis.md`. O timing do humor é decidido pelo **código**: o núcleo calcula `humor_permitido` (contexto sério, urgência, pressa do usuário, última piada recente) e só então o Falador pode tentar uma piada. Feedback "essa não deu" é registrado pra calibrar.

## Contexto e custo

- Falador: janela dos últimos turnos + resumo corrido; fecha a conversa por tempo parado ou mudança de assunto e grava resumo no vault.
- Trabalhador: uma sessão por tarefa, começando de um briefing; passou de um limite (turnos, tokens, tempo parado) → grava resumo no vault e a próxima chamada começa limpa. Checkpoints no inbox enquanto trabalha.
- Pacote de contexto por interação: persona + arquivo de estado atual (~1-2 mil tokens) + índice do vault + só o nó relevante.
- Travas: teto diário de gasto do Falador (`JARVIS_DAILY_BUDGET_USD`) e limite mensal da chave no console do provedor; contador de uso registrado. Aviso em ~80% do teto; no teto, para de chamar a API até liberar.

## Segurança e permissões

- Bot do Telegram só responde a IDs na allowlist; sem porta aberta (long polling).
- Começa **read-only**. Escreve só em `inbox/jarvis/`; integração no vault é feita depois, com confirmação humana, e **commit é sempre manual**.
- Meta: poucos cliques, em 3 faixas — livre (leitura, inbox), revisão interna (checagem barata antes de agir), pede confirmação (dinheiro, terceiros, apagar de verdade, publicar).
- Segredos só em `.env` (ignorado pelo git).

## Planejador diário (2026-10-15)

Um calendário de tarefas para o próximo mês, montado só com código (sem modelo), a partir do board do Mind. Sem horários e sem nada pra avisar durante o dia: o dono diz "concluí X" (ferramenta `concluir_tarefa`) e o Jarvis marca no plano e grava uma nota "concluída" no `inbox/jarvis/`, pro Claude propor marcar `[x]` no board. À meia-noite (ou ao subir, se o PC estava desligado) o planejador julga os dias que passaram: o que ficou aberto no board rola pro dia seguinte, na frente de tudo; o que sumiu do board conta como feito. A **capacidade** por dia começa em 3 (domingo 2, sábado 0, tempo sagrado) e acompanha a entrega: 2 dias seguidos com tudo feito sobe 1, 2 dias seguidos com sobra desce 1 (de 1 a 8). Quando o dono fecha todas as tarefas do dia, o Jarvis pergunta como está o tempo e se quer adiantar uma do dia seguinte. O plano de hoje fica estável durante o dia; os dias à frente são recalculados a cada refresh. Ordem de escolha: o que escorregou, prioridade/prazo (🔴 ou prazo em até 7 dias), lista por prioridade; ideias nunca; no máximo 2 tarefas por projeto no mesmo dia. Estado em `state/plano.json`. Comando: `/plano` (hoje) e `/plano semana`. Código: `plan.py` (modelo e armazém), `planner.py` (escolha, rolagem, "concluí"), `board.py` (leitor do board).

## Presença casa/fora

Três estados: em casa perto (mic + caixa), em casa longe do PC (só Telegram), fora (mic e caixa sempre desligados). Sinal principal: celular na Wi-Fi de casa; comando manual como reserva; histerese contra oscilação. Atividade no teclado sozinha engana (acesso remoto). Plano B se o Wi-Fi do celular dormir: o próprio celular avisa o bot (automação no Android). **A validar por experimento.**

## Resiliência (PC desligado / sem internet)

Batimento por minuto e registro da lacuna; mensagens do Telegram ficam guardadas até 24 h (depois perdem, e o Jarvis avisa); e-mail/agenda por cursor "último visto"; agendador com política de atraso (lembrete atrasado marcado, digest uma vez só); caixa de saída com validade por mensagem; resumo ao voltar; Windows subindo sozinho; alerta externo de queda opcional.

## Fases

0. **Protótipo de conversa por voz** (`prototype/`): falar, interromper, humor, latência.
1. **Núcleo + Telegram**: conversa na persona, anota no inbox, só leitura, fila pro Trabalhador.
2. **E-mail e agenda** (leitura), resumo do dia.
3. **Presença e handoff** com voz em casa.
4. **Proatividade** com escalonamento de avisos.
5. **App próprio** (Flutter ou PWA), widget, voz em tempo real fora de casa; depois ligação e outros canais.

## Estado da implementação (2026-10-12)

Fase 1 (núcleo + Telegram) funcionando, 459 testes, rodando no notebook de casa vigiado pela bandeja do Windows (`tray/`). Ainda sem Trabalhador, e-mail, agenda, resposta em voz nem política de contexto completa. Módulos em `src/jarvis/`:

| Módulo | O quê |
|---|---|
| `config.py` | Configuração por `.env` e ambiente, validação na partida (diz o nome do que falta, nunca o valor) |
| `bot.py` | Telegram: allowlist de IDs, comandos, áudio, botão "essa não deu", tratador de erro, reconexão na partida; nunca loga conteúdo nem token |
| `assistant.py` | Um turno: teto de gasto, trava de humor, persona, modelo, histórico, trava de ação (`has_intent`); desembrulha a piada de `[[humor: ...]]` |
| `actions.py`, `commands.py`, `help.py` | Ferramentas que o modelo nomeia (o código valida e responde), atalhos sem modelo e a lista única de comandos |
| `humor.py`, `style.py`, `tone.py` | Trava de humor, dicas de estilo sorteadas e limpeza do texto do modelo (markdown, aberturas e ofertas de ajuda) |
| `persona.py` + `persona/jarvis.md` | Prompt do Falador e seus marcadores de contexto |
| `budget.py`, `usage.py` | Contador e teto diário em JSON, custo por provedor, tela `/uso` |
| `conversation.py` | Histórico da conversa em disco (`state/conversa.json`), com trava |
| `mind.py`, `inbox.py`, `telegram_format.py` | Vault: tarefas pendentes (somente leitura) e notas no inbox (único lugar onde escreve) |
| `audio.py` | Transcrição de áudio do Telegram (Whisper do Groq, com prompt de vocabulário) |
| `when.py`, `repeat.py`, `reminder_request.py` | Datas em português (conjunto fechado: pergunta em vez de adivinhar), repetição e extração de quando/o quê/duração |
| `reminders.py`, `reminder_flow.py`, `conflicts.py`, `reminder_text.py` | Armazém (`state/lembretes.json`), conversa de pergunta e resposta, conflito entre lembretes e texto de entrega |
| `scheduler.py`, `outbox.py`, `heartbeat.py` | Agendador de 30 s, caixa de saída com roteador de canal (só Telegram por ora), batimento de 1 min e aviso de lacuna |
| `talker/` | Provedores (`anthropic`, `gemini`, `groq`) e `chain.py`, a cadeia com **disjuntor** (provedor que falhou descansa: 429 60 s, chave ruim 10 min, queda ou timeout 2 min). Contexto privado (títulos de tarefas) **nunca** vai pro Gemini grátis (`private_ok`). Timeout por provedor em `JARVIS_TALKER_TIMEOUT_S` |

Princípio que atravessa tudo: **o modelo só nomeia a ação, o código decide e responde**. Horário de lembrete vem das palavras do usuário lidas pelo código, ação que muda coisa só executa se o usuário pediu, e o que não é entendido vira pergunta, nunca palpite.

Pendente: ver a lista no board de tarefas do dono (prompt mais leve, política de contexto, agenda e e-mail, Trabalhador, voz). O `state/estado_atual.md` que o prompt reserva espaço ainda não é escrito por nada; decidir junto com a política de contexto.

## Em aberto

- Nome final do projeto.
- Se o Haiku sustenta o humor com a persona (medir no protótipo); preço do modelo atual a confirmar.
- Latência real ponta a ponta e orçamento de VRAM (Whisper + Kokoro).
- Se `pf_dora` roda no serviço de Kokoro do Pipecat.
- Estabilidade do sinal de presença do celular.
- Máquina 24/7 dedicada (não é pré-requisito das fases 0-1).
