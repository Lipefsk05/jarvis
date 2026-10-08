# Fase 0 — protótipo de conversa por voz

Objetivo: descobrir, antes de construir o resto, se a conversa por voz fica boa de verdade. Sem Telegram, sem Claude Code, sem vault. Só: falar, ele ouvir, responder em voz, e você poder interromper.

**Status: planejado, nada implementado.** Precisa de microfone e fone no PC de casa (Windows), então a parte de teste é feita com o Felipe na frente da máquina ou por acesso remoto com áudio.

## O que o protótipo precisa fazer

1. Ouvir continuamente com VAD e wake word (modelo pronto `hey_jarvis` do openWakeWord, só pra teste).
2. Usar **buffer circular** (pre-roll) pra a frase "Jarvis, você pode fazer…" funcionar sem esperar o sistema ativar.
3. Transcrever com faster-whisper (GPU).
4. Responder pelo Falador (API; provedor trocável) com `persona/jarvis.md`.
5. Falar com Kokoro (`pf_dora`) e com Piper, pra comparar.
6. Permitir **interrupção**: cortar a fala quando o usuário entra, e retomar se ainda fizer sentido.

## O que medir (registrar os números aqui)

| Medida | Como | Resultado |
|---|---|---|
| Latência fim da fala → início da resposta falada | cronômetro no log, média de várias falas | — |
| Tempo até a interrupção calar a voz | do início da fala do usuário até o silêncio | — |
| Acerto da wake word "Jarvis" com o sotaque do Felipe | acertos e falsos alarmes numa sessão | — |
| `pf_dora` funciona no Kokoro via Pipecat? | rodar | — |
| Kokoro vs Piper: qual soa melhor | ouvir lado a lado | — |
| Humor do Falador com a persona | 10 interações, anotar as que "não deram" | — |
| Uso de VRAM (Whisper + Kokoro) | `nvidia-smi` durante o uso | — |
| Custo por interação do Falador | contador de tokens da API | — |
| Eco com caixa de som vs fone | testar os dois | — |

## Ambiente

- Cliente de voz no **Python do Windows** (3.12 já instalado), em ambiente virtual; sem `uv` nem Ollama por enquanto.
- Dependências candidatas: Pipecat (com extras de VAD, Whisper e Kokoro), openWakeWord, cliente do provedor do Falador. Versões a fixar quando o protótipo for escrito.
- Chaves e token em `.env` (ver `config.example.env`).

## Fora do escopo desta fase

Telegram, Claude Code como Trabalhador, vault/inbox, presença casa/fora, agenda e e-mail.
