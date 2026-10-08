# Jarvis — desenho técnico

Documento vivo do desenho. Estado: **fase de desenho, sem código**. Atualizar quando uma decisão mudar.

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

- **Falador**: modelo rápido por API atrás de uma interface de provedor trocável (`anthropic` por padrão; `gemini` só em teste, porque o plano grátis pode usar o conteúdo enviado). Recebe persona + estado atual + últimos turnos + flag `humor_permitido`.
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

## Em aberto

- Nome final do projeto.
- Se o Haiku sustenta o humor com a persona (medir no protótipo); preço do modelo atual a confirmar.
- Latência real ponta a ponta e orçamento de VRAM (Whisper + Kokoro).
- Se `pf_dora` roda no serviço de Kokoro do Pipecat.
- Estabilidade do sinal de presença do celular.
- Máquina 24/7 dedicada (não é pré-requisito das fases 0-1).
