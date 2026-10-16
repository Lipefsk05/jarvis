# Fase 0 — protótipo de conversa por voz

Objetivo: descobrir, antes de construir o resto, se a conversa por voz fica boa de verdade. Sem Telegram, sem Claude Code, sem vault. Só: falar, ele ouvir, responder em voz, e você poder interromper.

**Status (2026-10-15): etapa 1 feita** (conversa por turnos, sem interrupção) em `prototype/voice/` — instalação em `prototype/voice/README.md`, rodar com `turn_loop.py`. Faltam a etapa 2 (interrupção) e a 3 (wake word com pre-roll). Teste com o Felipe na frente da máquina, microfone Logitech USB dedicado e caixa do notebook.

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
| Latência fim da fala → início da resposta falada | `turn_loop.py`, log em `turnos.csv` | **~2,4 s** (Whisper 0,75 + 1ª frase do modelo 0,6 + voz 1,05), medido pelo Felipe em 2026-10-15; antes do streaming eram ~3,4 s |
| Tempo até a interrupção calar a voz | do início da fala do usuário até o silêncio | — (etapa 2) |
| Acerto da wake word "Jarvis" com o sotaque do Felipe | acertos e falsos alarmes numa sessão | — (etapa 3) |
| `pf_dora` funciona no Kokoro? | rodar | **Sim** (via `kokoro-onnx`, `lang="pt-br"`), mas a pronúncia mistura português com inglês mal falado: **descartado** |
| Kokoro vs Piper: qual soa melhor | ouvir lado a lado | **Nenhum serve**: o Felipe não gostou de nenhum dos dois (Piper `faber` ainda confunde o Whisper) |
| Voz escolhida | ouvir Edge-TTS, Antonio (pt-BR) vs Duarte (pt-PT) | **Edge-TTS `pt-BR-AntonioNeural`** (grátis, online, API não oficial). Precisa de dicionário de pronúncias (`persona/pronuncias.json`) para Dindin, Firebase, backend. Filtro robótico leve testado (modulação em anel + eco curto) e **descartado**. Felipe acha que soa "voz do Google" mas **manteve** por ora; **Google Chirp 3 HD fica como possível mudança futura** (ativar o teste exigiu pré-pagamento de R$ 150 reembolsável; ver `voice/README.md`) |
| Humor do Falador com a persona | 10 interações, anotar as que "não deram" | — (falta amostra) |
| Uso de VRAM (Whisper + Kokoro) | `nvidia-smi` durante o uso | Whisper `large-v3-turbo` float16: **2,4 GB**; carga em 3,4 s e ~45 s de aquecimento da GPU na primeira vez (o `turn_loop.py` faz isso ao subir); transcreve uma frase em ~0,55 s. Como a voz é Edge-TTS (nuvem), não usa VRAM |
| Custo por interação do Falador | contador de tokens da API | — (Groq grátis; limite de 8.000 tokens/min) |
| Eco com caixa de som vs fone | testar os dois | — (etapa 2; na etapa 1 o Jarvis não ouve enquanto fala) |

**O que atrasa:** a voz (~1 s de ida e volta à nuvem por frase) e o Groq (~0,6 s). Já aplicado: resposta do modelo em streaming, voz começando na 1ª frase ou na 1ª vírgula, geração e reprodução em paralelo. Caminhos se precisar de mais: streaming de áudio de verdade (ElevenLabs Flash) ou voz local melhor.

## Ambiente

- Cliente de voz no **Python do Windows** (3.12), em ambiente virtual fora do repo; passo a passo em `voice/README.md`.
- Etapa 1 escrita **sem framework** (sounddevice + VAD por energia + faster-whisper + Edge-TTS + Groq por HTTP), para medir cada pedaço; Pipecat/LiveKit seguem como opção para a interrupção (etapa 2), se o laço manual não bastar.
- Chaves e token em `.env` (ver `config.example.env`).

## Fora do escopo desta fase

Telegram, Claude Code como Trabalhador, vault/inbox, presença casa/fora, agenda e e-mail.
