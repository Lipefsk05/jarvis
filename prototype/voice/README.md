# Ambiente de voz (Windows) — como instalar do zero

O cliente de voz roda no **Python do Windows** (microfone e caixa estão lá); o núcleo do Jarvis fica no WSL. Este passo a passo refaz o ambiente numa máquina nova. Tudo local e grátis.

## Requisitos
- Windows 11 com WSL2, Python 3.12 do Windows (`py -0p` lista), driver NVIDIA recente (a RTX 3050 de 6 GB serve; `nvidia-smi` tem que funcionar).
- ~5 GB livres no `C:` (venv ~2,5 GB, modelos ~0,4 GB, cache do Whisper ~1,6 GB).

## 1. Ambiente virtual (PowerShell)
Fora do WSL e fora do repo, no disco do Windows (rápido, e o repo mora em `\\wsl.localhost`):

```powershell
python -m venv C:\Users\felip\jarvis-voice-venv
C:\Users\felip\jarvis-voice-venv\Scripts\python.exe -m pip install --upgrade pip
C:\Users\felip\jarvis-voice-venv\Scripts\python.exe -m pip install sounddevice numpy soundfile requests faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12 kokoro-onnx piper-tts
```

`nvidia-cublas-cu12` e `nvidia-cudnn-cu12` trazem as DLLs de CUDA que o faster-whisper precisa (não precisa instalar o CUDA Toolkit); `common.py` as coloca no caminho.

## 2. Modelos de voz
Pasta: `C:\Users\felip\jarvis-voice-models` (no WSL: `/mnt/c/Users/felip/jarvis-voice-models`).

- **Kokoro** (de `thewh1teagle/kokoro-onnx`, release `model-files-v1.0`): `kokoro-v1.0.onnx` (~310 MB) e `voices-v1.0.bin` (~27 MB). No WSL:
  ```bash
  curl -L -o /mnt/c/Users/felip/jarvis-voice-models/kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
  curl -L -o /mnt/c/Users/felip/jarvis-voice-models/voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
  ```
  No PowerShell o mesmo vale com `curl.exe` e caminhos com barra invertida (no bash do WSL as barras invertidas se perdem).
- **Piper** (`pt_BR-faber-medium.onnx` e `.onnx.json`): copiados de `joee/training/piper_voices/`; também saem do repo `rhasspy/piper-voices` (Hugging Face), pasta `pt/pt_BR/faber/medium`.
- **Whisper** (`large-v3-turbo`): baixa sozinho na primeira execução do `bench_stt.py` (cache do Hugging Face, ~1,6 GB).

## 3. Rodar (a partir de qualquer terminal)
```powershell
cd \\wsl.localhost\Ubuntu\home\felip\projetos\jarvis\prototype\voice
C:\Users\felip\jarvis-voice-venv\Scripts\python.exe bench_tts.py --play
C:\Users\felip\jarvis-voice-venv\Scripts\python.exe bench_stt.py
```
Do WSL: `powershell.exe -NoProfile -Command "& 'C:\Users\felip\jarvis-voice-venv\Scripts\python.exe' bench_tts.py"`. Os WAVs saem em `C:\Users\felip\jarvis-voice-out`.

## Etapa 2: conversa com interrupção (`talk.py`, 2026-10-20)

Microfone **sempre aberto**: o Jarvis fala e você pode falar por cima dele. Sem framework (só `sounddevice`); a detecção de voz é o **Silero VAD que já vem dentro do `faster-whisper`**, quadro a quadro (`duplex.py`, com testes em `test_duplex.py`).

```powershell
cd \\wsl.localhost\Ubuntu\home\felip\projetos\jarvis\prototype\voice
C:\Users\felip\jarvis-voice-venv\Scripts\python.exe talk.py            # Enter abre a conversa; fale; "tchau" encerra
C:\Users\felip\jarvis-voice-venv\Scripts\python.exe talk.py --list     # lista os dispositivos de áudio
C:\Users\felip\jarvis-voice-venv\Scripts\python.exe talk.py --out Realtek   # escolhe a saída por parte do nome
C:\Users\felip\jarvis-voice-venv\Scripts\python.exe talk.py --simulate  # sem microfone: vozes sintéticas provam a interrupção
C:\Users\felip\jarvis-voice-venv\Scripts\python.exe -m unittest test_duplex
```

- **Use fone, de preferência por cabo**: com caixa de som o microfone ouve o Jarvis e ele se interrompe sozinho; no Bluetooth a saída atrasa 150-250 ms. O microfone é o USB (Logitech); o fone só toca.
- **Interromper** exige ~0,4 s de voz contínua (`BARGE_IN_S`), pra um "aham" ou uma tosse não cortar a fala; começar uma frase com o Jarvis calado exige 0,2 s (`START_S`); a frase termina após 0,7 s de silêncio (`SILENCE_S`). Tudo em `duplex.py`.
- Ao ser cortado o Jarvis **para na hora** (esvazia o buffer de saída, cancela o modelo e a voz) e **não retoma**; no histórico fica só o que ele chegou a dizer, marcado "[o senhor interrompeu]". O que você falou por cima vira o próximo turno.
- Fim da conversa: "tchau" / "até logo" / "encerra", ou 20 s de silêncio (`--idle`).
- Medido na simulação: a fala por cima começou em 15,0 s e a do Jarvis foi cortada em 15,6 s (0,4 s de limite + atraso do quadro).

## Voz do Google (Chirp 3 HD) — NÃO adotado, possível mudança futura (2026-10-15)
**Situação:** ao ativar o teste grátis (US$ 300, 90 dias), o cartão Elo do Felipe exigiu um **pré-pagamento único de R$ 150**, reembolsável se fechar a conta de faturamento (prazo e regras não vistos; ler o link "Learn more about payment methods" da tela). Ele parou e manteve o Edge-TTS. O projeto `jarvis-voz-511802` existe, sem faturamento. Quando retomar, decidir os R$ 150 (conta pré-paga só gasta o saldo, uma trava natural) ou tentar outro cartão; sem conta de faturamento a API não funciona.

Passos, se for adiante. Escolhida para testar porque dá **1 milhão de caracteres grátis por mês** (~15 h de fala); depois disso são US$ 30 por milhão, **cobrados sozinhos** se passar. Por isso o teto rígido é parte da configuração:

1. Em <https://console.cloud.google.com> crie um **projeto novo** só pra isso (ex.: `jarvis-voz`).
2. **Faturamento**: vincule uma conta de faturamento ao projeto (pede cartão; o grátis só vale em conta paga).
3. **Orçamento com teto**: Faturamento > Orçamentos e alertas > Criar orçamento. Escopo: só este projeto. Valor: R$ 1 (ou o mínimo). Alertas em 50%, 90% e 100% por e-mail. Se aparecer a opção **"Spend cap"/aplicar teto**, ligue: ao bater o teto a API passa a recusar o uso. Se não aparecer, o orçamento só avisa (não bloqueia): nesse caso, olhe o uso do mês de vez em quando.
4. **Ativar a API**: APIs e serviços > Biblioteca > "Cloud Text-to-Speech API" > Ativar.
5. **Chave**: APIs e serviços > Credenciais > Criar credenciais > Chave de API. Em "Restrições de API", limite a **Cloud Text-to-Speech API**. Copie a chave para o `.env` do repo como `GOOGLE_TTS_API_KEY=...` (o arquivo fica fora do git).
6. Teste: `python bench_google.py --list` (lista as vozes pt-BR Chirp 3 HD) e `python bench_google.py` (toca 3 vozes masculinas).

O custo é por caractere enviado (conta espaços); a resposta do Jarvis por voz tem ~100 a 300 caracteres.

## Dispositivos de áudio (esta máquina, 2026-10-15)
Microfones: Logitech USB Microphone (dedicado), Intel Smart Sound (do notebook). Caixa: Realtek. Fone Bluetooth QCY evitado nos testes (microfone ruim e latência na troca de perfil).

## Armadilhas já vistas
- Copiar comando de `curl.exe ... C:\Users\...` pro **bash do WSL** perde as barras invertidas e dá "Permission denied": no WSL use `/mnt/c/...`.
- No PowerShell, `curl` puro é outro comando (alias de `Invoke-WebRequest`): use `curl.exe`.
- `nvidia-smi` dentro do WSL e no Windows enxergam a mesma GPU; os 6 GB são divididos entre Whisper e Kokoro.
