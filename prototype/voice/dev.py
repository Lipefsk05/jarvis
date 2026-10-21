"""Dev mode of the voice prototype ("modo dev" on, "modo casual" off): the owner talks and the work happens in the Mind
with the full Claude Code behind it, but the voice is always the Jarvis: nothing spoken or sent ever names the tool.

    - one `claude -p` call per sentence, the same session continued with --resume (so it is a conversation);
    - runs in the Mind (the hub; the other projects are reached through the Mind's additionalDirectories) with the
      owner's own settings, so it follows the same rules as the terminal;
    - reads and edits freely; Bash only for an allowlist. What it is denied comes back as `permission_denials`: the
      Jarvis asks out loud, and "sempre" saves a narrow rule (a command, never "all of Bash"); push, force, rm -rf,
      sudo, commit... are asked every time;
    - spoken progress lines while it works, never the same twice in a row; a ceiling per sentence (on by default).

Pure logic and one subprocess wrapper, so the tests need no audio and no network (stdlib only)."""
import json
import random
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

MIND_DIR = "/home/felip/projetos/mind"
CLAUDE = "/home/felip/.local/bin/claude"
# --exec runs the program with no shell in between: through the default shell, the parentheses of a rule like
# `Bash(git status:*)` were a syntax error and the work never started (found in the first real test, 2026-10-21).
# The same PATH as his terminal (nvm's node, ~/.local/bin): through plain `wsl.exe` it was missing and the work used the
# system's npm 9.2.0 instead of his 10.8.2 (found in the 2nd real test). `bash -c '...' _ args` keeps the arguments intact.
_PATH_FIX = ('v=$(cat "$HOME/.nvm/alias/default" 2>/dev/null); '
             'n=$(ls -d "$HOME"/.nvm/versions/node/v"$v"*/bin 2>/dev/null | tail -1); '
             '[ -n "$n" ] || n=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | tail -1); '
             'export PATH="$n:$HOME/.local/bin:$PATH"; exec "$@"')
WSL_PREFIX = ["wsl.exe", "-d", "Ubuntu", "--cd", MIND_DIR, "--exec", "bash", "-c", _PATH_FIX, "_"]
BRIEFING_FILE = "/home/felip/projetos/jarvis/state/dev-briefing.txt"  # the instructions travel in a file, not on the command line
CEILING_S = 600.0                 # per sentence, from the question to the answer (thinking, reading, editing, tests)
NOTICE_S = 300.0                  # at half the ceiling the Jarvis says it is still working

BASE_ALLOW = (
    "Read", "Glob", "Grep",
    "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)", "Bash(git branch:*)",
    "Bash(ls:*)", "Bash(.venv/bin/python -m unittest:*)", "Bash(python3 -m unittest:*)", "Bash(npm test:*)",
)

DEV_BRIEFING = (
    "Você é o Jarvis, assistente pessoal do Felipe, falando por voz. Fale sempre em primeira pessoa, como o Jarvis "
    "(\"senhor\" com formalidade leve), e NUNCA cite Claude, Claude Code, modelo, ferramenta, comando interno ou o nome "
    "de qualquer tool: o senhor não quer saber como o trabalho é feito, só que você o faz. Seu cwd é o Mind dele e os "
    "outros projetos estão disponíveis como diretórios adicionais. Siga as regras de trabalho dele (git direto em main, "
    "nunca commitar nem dar push sem ele pedir). FORMATO DA RESPOSTA FINAL: primeiro um resumo falado de 3 a 5 frases curtas, "
    "em português corrido, sem markdown, sem código, sem caminhos longos, dizendo o que fez e o que falta; depois, só se "
    "houver detalhe que vale guardar, uma linha com exatamente --- e o texto completo (arquivos mexidos, trechos, "
    "comandos). O texto do senhor vem de uma transcrição de voz: nomes de arquivo e de projeto podem chegar errados (\"do plex\" "
    "é duplex); antes de dizer que não achou um arquivo, procure o nome mais provável. Se precisar de uma permissão que não tem, diga numa frase o que precisaria, sem rodeio."
)

# --- mode and settings by voice ----------------------------------------------------------------------------

# Only "modo dev" and close spellings of it: a whole garbled sentence ("como é o do deve?") is deliberately not rescued.
_DEV_ON = re.compile(r"\b(?:modo|mode) (?:dev|deve|devi|dive|def|desenvolvedor|desenvolvimento)\b")
_CASUAL = re.compile(r"\bmodo (?:casual|normal|conversa)\b")
_CEILING_OFF = re.compile(r"\b(?:tir\w+|retir\w+|remov\w+|deslig\w+|desativ\w+|sem)\b.*\bteto\b|\bteto\b.*\b(?:desligado|desativado|off)\b")
_CEILING_ON = re.compile(r"\b(?:poe|ponha|coloca|liga|ativa|volta)\b.*\bteto\b")
_LIST_ALLOWED = re.compile(r"\bo que (?:eu )?autoriz\w+\b|\bquais (?:autorizacoes|permissoes)\b|\blista\w* (?:as )?(?:autorizacoes|permissoes)\b")
_REVOKE = re.compile(r"\b(?:revog\w+|tir\w+|retir\w+|remov\w+|apag\w+)\b.*\b(?:autorizacao|permissao)\b(?: (?:do|da|de|dos|das))?\s*(.*)$")


def _fold(text: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


# Names of the owner's files and projects that the Whisper splits or garbles; fixed before the sentence goes to the work.
_MISHEARD = (
    (re.compile(r"\bnpm[\s-]*(?:menos[\s-]*){1,2}(\w+)\b", re.IGNORECASE), r"npm --\1"),
    (re.compile(r"\bnpm[\s-]+version\b", re.IGNORECASE), "npm --version"),
    (re.compile(r"\b(?:d[oa]|de|espaco|espa\w+) ?plex\b", re.IGNORECASE), "duplex"),
    (re.compile(r"\bdu ?plex\b", re.IGNORECASE), "duplex"),
)


def fix_names(text: str) -> str:
    """The sentence with known mishearings of file names put right ("do plex.py" -> "duplex.py")."""
    folded = _fold(text)
    for pattern, right in _MISHEARD:
        if pattern.search(folded):
            # folding only drops combining marks, so the match positions are the same in the original text
            text = pattern.sub(right, folded) if len(folded) != len(text) else _sub_at(text, folded, pattern, right)
    return text


def _sub_at(original: str, folded: str, pattern, right: str) -> str:
    out, last = [], 0
    for match in pattern.finditer(folded):
        out += [original[last:match.start()], match.expand(right)]
        last = match.end()
    return "".join(out) + original[last:]


def parse_mode(text: str) -> str | None:
    """"dev" / "casual" when the sentence switches the mode, else None."""
    folded = _fold(text)
    if len(folded.split()) > 6:
        return None  # "olha o arquivo e me diz como funciona o modo dev" is a request that mentions it, not the switch
    if _CASUAL.search(folded):
        return "casual"
    return "dev" if _DEV_ON.search(folded) else None


_STOP_ALL = re.compile(r"\bpara tudo\b|\bcancela tudo\b|\bencerra tudo\b")
_STOP = re.compile(r"\b(?:para|pare|cancela|cancele|aborta|aborte|deixa pra la|deixa isso|esquece|esqueca|chega)\b")
_CONTINUE = re.compile(r"\b(?:continua|continue|segue|siga|retoma|retome|prossegue|prossiga|pode continuar|pode seguir|pode falar)\b")
_STATUS = re.compile(r"\bcomo (?:esta|ta|anda|vai)\b|\bja (?:acabou|terminou|esta pronto)\b|\bo que (?:voce )?esta fazendo\b|\bqual o status\b")


def parse_job_command(text: str) -> str | None:
    """A short command to the work that is running: "stop_all", "stop", "continue" (the voice goes on) or "status"."""
    folded = _fold(text)
    if len(folded.split()) > 7:
        return None  # a longer sentence is a new request, not a command
    for name, pattern in (("stop_all", _STOP_ALL), ("stop", _STOP), ("continue", _CONTINUE), ("status", _STATUS)):
        if pattern.search(folded):
            return name
    return None


def label_for(request: str, words: int = 5) -> str:
    """A short name for a job, from the first words of what the owner asked ("olha o duplex e me diz o que ele faz" -> ...)."""
    cleaned = re.sub(r"[^\w\s.-]", "", fix_names(request)).split()
    return " ".join(cleaned[:words]) or "o último pedido"


def parse_setting(text: str) -> tuple[str, str] | None:
    """A settings command spoken in dev mode: ("ceiling_off"|"ceiling_on"|"list"|"revoke", argument)."""
    folded = _fold(text)
    revoke = _REVOKE.search(folded)
    if revoke:
        return "revoke", revoke.group(1).strip(" .,")
    if _CEILING_OFF.search(folded):
        return "ceiling_off", ""
    if _CEILING_ON.search(folded):
        return "ceiling_on", ""
    if _LIST_ALLOWED.search(folded):
        return "list", ""
    return None


# --- permissions: what is asked, what is remembered ---------------------------------------------------------

_COMPOUND = re.compile(r"&&|\|\||[;|`<>]|\$\(")
_ALWAYS_ASK = re.compile(
    r"(?:^|\s)(?:push|commit|rebase|merge|tag|rm|rmdir|mv|sudo|su|chmod|chown|kill|pkill|killall|shutdown|reboot|dd|mkfs|"
    r"curl|wget|ssh|scp|rsync|eval|exec|docker|systemctl)(?:\s|$)|--force|--hard|-rf?\b|\bgit\s+(?:reset|clean|checkout|restore)\b"
)
_SAFE_PREFIX = (
    re.compile(r"^(git (?:status|diff|log|show|branch|add))\b"),
    re.compile(r"^(npm (?:test|run test|run build|run lint))\b"),
    re.compile(r"^(\S*python3? -m (?:unittest|pytest))\b"),
)


def never_forever(denial: dict) -> bool:
    """True when "sempre" is not offered: a risky command, a chained one, or any tool other than a plain Bash command."""
    if denial.get("tool_name") != "Bash":
        return True
    command = str(denial.get("tool_input", {}).get("command", ""))
    return bool(_COMPOUND.search(command) or _ALWAYS_ASK.search(" " + command + " "))


def rule_for(denial: dict) -> str | None:
    """The narrow rule to save for "sempre" (a safe prefix like `git status`, else the exact command), or None."""
    if never_forever(denial):
        return None
    command = str(denial["tool_input"].get("command", "")).strip()
    if not command:
        return None
    for pattern in _SAFE_PREFIX:
        found = pattern.match(command)
        if found:
            return f"Bash({found.group(1)}:*)"
    return f"Bash({command})"


# --- what the owner's own settings already decided ---------------------------------------------------------

SETTINGS_FILES = ("/home/felip/.claude/settings.json", "/home/felip/.claude/settings.local.json",
                  f"{MIND_DIR}/.claude/settings.json", f"{MIND_DIR}/.claude/settings.local.json")


def settings_rules(kind: str, files: tuple = SETTINGS_FILES) -> list[str]:
    """The `deny` or `ask` rules of his Claude Code settings (a missing or odd file is skipped)."""
    rules: list[str] = []
    for name in files:
        path = Path(r"\\wsl.localhost\Ubuntu" + name) if sys.platform == "win32" else Path(name)
        try:
            rules += [str(r) for r in json.loads(path.read_text(encoding="utf-8")).get("permissions", {}).get(kind, [])]
        except (OSError, ValueError, AttributeError):
            continue
    return rules


def _rule_matches(rule: str, denial: dict) -> bool:
    import fnmatch
    tool, data = denial.get("tool_name", ""), denial.get("tool_input", {}) or {}
    if not rule.startswith(tool + "(") or not rule.endswith(")"):
        return False
    inner = rule[len(tool) + 1:-1]
    if tool == "Bash":
        command = " ".join(str(data.get("command", "")).split())
        if inner.endswith(":*"):
            return command == inner[:-2] or command.startswith(inner[:-2] + " ")
        return fnmatch.fnmatchcase(command, inner)
    target = str(data.get("file_path", data.get("path", "")))
    return fnmatch.fnmatchcase(target, inner) or (inner.startswith("**/") and fnmatch.fnmatchcase(target, "*" + inner[2:]))


def classify(denial: dict, deny: list[str], ask: list[str]) -> str:
    """"deny" (his settings forbid it: no "sim" can change that), "ask" (his settings want his own approval, which a
    spoken "sim" does not give) or "open" (just not allowed yet: a "sim" can allow it)."""
    if any(_rule_matches(r, denial) for r in deny):
        return "deny"
    return "ask" if any(_rule_matches(r, denial) for r in ask) else "open"


def describe(denial: dict) -> str:
    """What was denied, as a spoken phrase for the question ("rodar o comando ..."), never naming the tool."""
    tool, data = denial.get("tool_name", ""), denial.get("tool_input", {}) or {}
    if tool == "Bash":
        words = str(data.get("command", "")).split()
        head = " ".join(words[:2]) if words[:1] in (["git"], ["npm"], ["docker"]) else " ".join(words[:1])
        return f"rodar o comando {head}".strip()  # the flags would be noise out loud; the full command goes to the log
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return "escrever em " + Path(str(data.get("file_path", "um arquivo"))).name
    if tool in ("WebFetch", "WebSearch"):
        return "buscar uma coisa na internet"
    return "fazer uma coisa que não está liberada"


@dataclass
class Settings:
    """What the owner chose, kept in a small JSON file (later this moves to the interface): the ceiling and the rules
    he said "sempre" to."""
    path: Path
    ceiling: bool = True
    ceiling_s: float = CEILING_S
    allow: list = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Settings":
        settings = cls(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            settings.ceiling = bool(raw.get("ceiling", True))
            settings.ceiling_s = float(raw.get("ceiling_s", CEILING_S))
            settings.allow = [str(r) for r in raw.get("allow", []) if str(r).startswith("Bash(")]
        except (OSError, ValueError):
            pass
        return settings

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"ceiling": self.ceiling, "ceiling_s": self.ceiling_s, "allow": self.allow},
                                        ensure_ascii=False, indent=1), encoding="utf-8")

    def remember(self, rule: str) -> None:
        if rule not in self.allow and rule not in BASE_ALLOW:
            self.allow.append(rule)
            self.save()

    def revoke(self, term: str) -> list[str]:
        """Drop the saved rules that contain `term` (all of them when it is empty? never: an empty term drops nothing)."""
        if not term:
            return []
        gone = [r for r in self.allow if _fold(term) in _fold(r)]
        self.allow = [r for r in self.allow if r not in gone]
        if gone:
            self.save()
        return gone

    def tools(self, session_extra: list[str]) -> list[str]:
        return list(dict.fromkeys([*BASE_ALLOW, *self.allow, *session_extra]))

    def listing(self) -> str:
        saved = [r.removeprefix("Bash(").removesuffix(")").removesuffix(":*") for r in self.allow]
        return ("Além do básico (ler, editar e consultar o git), o senhor autorizou: " + "; ".join(saved) + "."
                if saved else "Só o básico, senhor: ler, editar e consultar o git. Nada mais foi autorizado.")


# --- spoken progress ---------------------------------------------------------------------------------------

THINKING = (
    "Vou analisar isso, senhor, um momento.", "Deixe-me ver isso, senhor.", "Um instante, senhor.",
    "Permita-me verificar, senhor.", "Vou dar uma olhada, senhor.", "Certo, senhor, vou verificar.",
    "Só um momento, senhor, estou vendo isso.",
)
STILL = (
    "Ainda estou nisso, senhor, só mais um momento.", "Está levando um pouco mais que o esperado, senhor.",
    "Continuo verificando, senhor.", "Peço um pouco de paciência, senhor, ainda estou trabalhando.",
    "Segue em andamento, senhor.",
)
READING = ("Estou lendo o {name}, senhor.", "Dando uma olhada no {name}.", "Vou ler o {name} com calma, senhor.")
EDITING = ("Estou ajustando o {name}, senhor.", "Fazendo a mudança no {name}.", "Mexendo no {name} agora, senhor.")
SEARCHING = ("Estou procurando isso nos arquivos, senhor.", "Procurando por aqui, senhor.", "Vasculhando os arquivos, senhor.")
RUNNING = ("Vou rodar uma verificação, senhor.", "Executando um teste, senhor.", "Rodando um comando, senhor.")
WEB = ("Estou pesquisando por fora, senhor.", "Consultando a internet, senhor.", "Buscando isso na rede, senhor.")


def pick(pool: tuple, last: str | None, rng=random) -> str:
    options = [p for p in pool if p != last] or list(pool)
    return rng.choice(options)


def progress_line(tool: str, data: dict, last: str | None = None, rng=random) -> str | None:
    """A short spoken line for what is being done, or None when the tool is not worth announcing."""
    name = Path(str(data.get("file_path", data.get("path", "")))).stem or "o arquivo"
    if tool == "Read":
        template = pick(READING, last and last.replace(name, "{name}"), rng)
    elif tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        template = pick(EDITING, last and last.replace(name, "{name}"), rng)
    elif tool in ("Grep", "Glob"):
        template = pick(SEARCHING, last, rng)
    elif tool == "Bash":
        template = pick(RUNNING, last, rng)
    elif tool in ("WebSearch", "WebFetch"):
        template = pick(WEB, last, rng)
    else:
        return None
    return template.format(name=name)


# --- the call ----------------------------------------------------------------------------------------------

@dataclass
class TurnResult:
    text: str = ""
    session_id: str | None = None
    denials: list = field(default_factory=list)
    seconds: float = 0.0
    timed_out: bool = False
    cancelled: bool = False
    early_denial: bool = False   # stopped at the first denied tool: the rest of the turn would only be the work flailing around it
    error: str = ""


def split_reply(text: str) -> tuple[str, str]:
    """(spoken, full): the part before a line with just `---` is what is spoken; the whole text goes to the Telegram."""
    text = text.strip()
    head, sep, tail = text.partition("\n---\n")
    spoken = head.strip() if sep else text
    if len(spoken) > 700 and not sep:  # no separator and long: speak the first sentences, keep the rest for reading
        cut = spoken[:700]
        spoken = cut[:max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "), 0) + 1] or cut
    return spoken, text


_MARKDOWN_BLOCK = re.compile(r"^\s*(?:[-*•]\s|#{1,6}\s|\d+[.)]\s|\*\*|```|\|)")


def speakable(text: str, max_sentences: int = 5) -> str:
    """The part of the reply fit to be spoken: stops where a list, heading, table or code starts (that is for reading),
    drops markdown marks, keeps at most `max_sentences`."""
    kept = []
    for line in text.strip().splitlines():
        if _MARKDOWN_BLOCK.match(line) and kept:
            break
        kept.append(line)
    plain = " ".join(" ".join(kept).replace("`", "").replace("**", "").replace("*", "").replace("#", "").split())
    sentences = re.split(r"(?<=[.!?])\s+", plain)
    return " ".join(sentences[:max_sentences]).strip()


def build_command(session_id: str | None, tools: list[str], windows: bool | None = None) -> list[str]:
    windows = sys.platform == "win32" if windows is None else windows
    command = ([*WSL_PREFIX] if windows else []) + [
        CLAUDE, "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits",
        "--setting-sources", "user,project", "--append-system-prompt-file", BRIEFING_FILE,
    ]
    if session_id:
        command += ["--resume", session_id]
    return command + ["--allowedTools", *tools]


def write_briefing(path: str = BRIEFING_FILE) -> None:
    """Keep the instructions file in step with DEV_BRIEFING (written from either side; the file lives in the repo's state)."""
    target = Path(r"\\wsl.localhost\Ubuntu" + path) if sys.platform == "win32" else Path(path)  # the Windows side sees WSL by UNC
    if not target.exists() or target.read_text(encoding="utf-8") != DEV_BRIEFING:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(DEV_BRIEFING, encoding="utf-8")


_DENIED = re.compile(r"requires approval|has been denied|haven't granted it yet|requested permissions")
_GATED_TOOLS = ("Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch")


def run_turn(prompt: str, session_id: str | None, tools: list[str], ceiling_s: float | None, on_tool, cancelled: threading.Event,
             popen=subprocess.Popen, windows: bool | None = None) -> TurnResult:
    """One sentence of the conversation. `on_tool(name, input)` is called for each tool the work uses (to announce it);
    `cancelled` (the owner called the Jarvis by name) kills it; `ceiling_s=None` means no ceiling."""
    started = time.perf_counter()
    result = TurnResult()
    try:
        proc = popen(build_command(session_id, tools, windows), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.STDOUT, text=True, encoding="utf-8", cwd=None if (sys.platform == "win32" if windows is None else windows) else MIND_DIR)
    except OSError as exc:
        return TurnResult(error=f"não consegui iniciar o trabalho ({type(exc).__name__})")
    state = {"timed_out": False}
    uses: dict[str, tuple[str, dict]] = {}  # tool_use id -> (name, input), to know what a denial was about

    def watchdog() -> None:
        while proc.poll() is None:
            if cancelled.is_set():
                result.cancelled = True
                proc.kill()
                return
            if ceiling_s is not None and time.perf_counter() - started > ceiling_s:
                state["timed_out"] = True
                proc.kill()
                return
            time.sleep(0.25)

    threading.Thread(target=watchdog, daemon=True).start()
    try:
        proc.stdin.write(prompt)
        proc.stdin.close()
    except OSError:
        pass
    stray: list[str] = []  # lines that are not events (a launch error from the shell or the program), for the error message
    for line in proc.stdout:
        try:
            event = json.loads(line)
        except ValueError:
            if line.strip():
                stray = (stray + [line.strip()])[-4:]
            continue
        kind = event.get("type")
        if kind == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    uses[block.get("id", "")] = (block.get("name", ""), block.get("input", {}) or {})
                    on_tool(block.get("name", ""), block.get("input", {}) or {})
        elif kind == "user" and not result.early_denial:
            for block in event.get("message", {}).get("content", []):
                used = uses.get(block.get("tool_use_id", "")) if isinstance(block, dict) else None
                if (used and block.get("is_error") and used[0] in _GATED_TOOLS
                        and _DENIED.search(str(block.get("content", "")))):
                    # the first denial ends the turn: the Jarvis asks right away instead of the work trying other ways for a minute
                    result.denials = [{"tool_name": used[0], "tool_input": used[1], "tool_use_id": block.get("tool_use_id")}]
                    result.early_denial = True
                    proc.kill()
                    break
        elif kind == "system" and event.get("session_id") and not result.session_id:
            result.session_id = event.get("session_id")  # known from the start, so a turn stopped early can still be resumed
        elif kind == "result":
            result.text = str(event.get("result", ""))
            result.session_id = event.get("session_id")
            result.denials = list(event.get("permission_denials") or [])
            if event.get("is_error"):
                result.error = result.text or "o trabalho terminou com erro"
    proc.wait()
    if not result.text and not result.error and not state["timed_out"] and not result.cancelled and not result.early_denial:
        result.error = " | ".join(stray) or f"o trabalho terminou sem resposta (código {proc.returncode})"  # never silent: the owner must hear that it failed
    result.seconds = time.perf_counter() - started
    result.timed_out = state["timed_out"]
    return result


# --- the Telegram copy -------------------------------------------------------------------------------------

def send_telegram(token: str, chat_id: str, text: str, opener=urllib.request.urlopen) -> bool:
    """The full text to the owner's Telegram (the voice only speaks the summary). Never raises."""
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:3900]}).encode()
    try:
        with opener(urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data), timeout=15):
            return True
    except Exception:
        return False
