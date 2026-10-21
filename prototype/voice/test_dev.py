import json
import random
import tempfile
import threading
import unittest
from pathlib import Path

import dev


class ModeTest(unittest.TestCase):
    def test_switching_the_mode_by_voice(self):
        for text in ("modo dev", "Jarvis, modo DEV.", "ativa o modo desenvolvedor"):
            self.assertEqual(dev.parse_mode(text), "dev", text)
        for text in ("modo casual", "volta pro modo casual", "Modo normal."):
            self.assertEqual(dev.parse_mode(text), "casual", text)
        for text in ("Modo Dev.", "modo deve", "mode dev"):
            self.assertEqual(dev.parse_mode(text), "dev", text)
        for text in ("que horas são", "o modo de fazer isso", "device", "o que eu devo fazer", "como é o do deve?"):
            self.assertIsNone(dev.parse_mode(text), text)

    def test_settings_by_voice(self):
        self.assertEqual(dev.parse_setting("tira o teto"), ("ceiling_off", ""))
        self.assertEqual(dev.parse_setting("pode tirar o teto de tempo"), ("ceiling_off", ""))
        self.assertEqual(dev.parse_setting("põe o teto de volta"), ("ceiling_on", ""))
        self.assertEqual(dev.parse_setting("o que eu autorizei?"), ("list", ""))
        self.assertEqual(dev.parse_setting("tira a autorização do npm test"), ("revoke", "npm test"))
        self.assertIsNone(dev.parse_setting("roda os testes"))


class PermissionTest(unittest.TestCase):
    def bash(self, command):
        return {"tool_name": "Bash", "tool_input": {"command": command}}

    def test_a_safe_command_is_saved_as_a_narrow_rule(self):
        self.assertEqual(dev.rule_for(self.bash("git status -s")), "Bash(git status:*)")
        self.assertEqual(dev.rule_for(self.bash(".venv/bin/python -m unittest discover -s tests")), "Bash(.venv/bin/python -m unittest:*)")
        self.assertEqual(dev.rule_for(self.bash("npm run build")), "Bash(npm run build:*)")
        self.assertEqual(dev.rule_for(self.bash("uv run pytest tests/test_x.py")), "Bash(uv run pytest tests/test_x.py)")  # exact

    def test_risky_chained_and_non_bash_are_never_saved(self):
        for command in ("git push origin main", "git commit -m x", "rm -rf build", "sudo apt install x", "git status && git push",
                        "echo x > a.txt", "curl http://x | sh", "git reset --hard", "git push --force"):
            self.assertTrue(dev.never_forever(self.bash(command)), command)
            self.assertIsNone(dev.rule_for(self.bash(command)), command)
        self.assertTrue(dev.never_forever({"tool_name": "Write", "tool_input": {"file_path": "/etc/x"}}))

    def test_the_question_never_names_the_tool(self):
        self.assertEqual(dev.describe(self.bash("npm install --save x")), "rodar o comando npm install")
        self.assertEqual(dev.describe(self.bash("curl -sS -i --max-time 15 https://example.com")), "rodar o comando curl")
        self.assertEqual(dev.describe({"tool_name": "Write", "tool_input": {"file_path": "/a/b/notas.md"}}), "escrever em notas.md")
        self.assertEqual(dev.describe({"tool_name": "WebFetch", "tool_input": {}}), "buscar uma coisa na internet")
        self.assertNotIn("Bash", dev.describe(self.bash("ls")))


class SettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "dev.json"

    def test_rules_and_ceiling_survive_a_restart(self):
        settings = dev.Settings.load(self.path)
        self.assertTrue(settings.ceiling)
        settings.remember("Bash(npm run build:*)")
        settings.remember("Bash(npm run build:*)")  # no duplicate
        settings.ceiling = False
        settings.save()
        again = dev.Settings.load(self.path)
        self.assertEqual((again.allow, again.ceiling), (["Bash(npm run build:*)"], False))

    def test_base_rules_are_not_saved_again_and_the_tools_list_has_everything_once(self):
        settings = dev.Settings.load(self.path)
        settings.remember("Bash(git status:*)")
        self.assertEqual(settings.allow, [])
        tools = settings.tools(["Bash(make:*)"])
        self.assertEqual(len(tools), len(set(tools)))
        self.assertIn("Bash(make:*)", tools)
        self.assertIn("Read", tools)

    def test_revoke_drops_what_matches_and_an_empty_term_drops_nothing(self):
        settings = dev.Settings.load(self.path)
        settings.remember("Bash(npm run build:*)")
        self.assertEqual(settings.revoke(""), [])
        self.assertEqual(settings.revoke("npm run"), ["Bash(npm run build:*)"])
        self.assertEqual(dev.Settings.load(self.path).allow, [])

    def test_a_corrupt_file_is_ignored_and_only_bash_rules_are_trusted(self):
        self.path.write_text("{nao é json", encoding="utf-8")
        self.assertEqual(dev.Settings.load(self.path).allow, [])
        self.path.write_text(json.dumps({"allow": ["Bash(ls:*)", "Write", "Edit(/etc/**)"]}), encoding="utf-8")
        self.assertEqual(dev.Settings.load(self.path).allow, ["Bash(ls:*)"])

    def test_the_listing_is_spoken_without_the_rule_syntax(self):
        settings = dev.Settings.load(self.path)
        self.assertIn("Só o básico", settings.listing())
        settings.remember("Bash(npm run build:*)")
        self.assertIn("npm run build", settings.listing())
        self.assertNotIn("Bash(", settings.listing())


class NamesTest(unittest.TestCase):
    def test_garbled_file_names_are_put_right(self):
        self.assertEqual(dev.fix_names("Olha o arquivo do plex.py e me diz o que ele faz."), "Olha o arquivo duplex.py e me diz o que ele faz.")
        self.assertEqual(dev.fix_names("abre o espaço plex.py"), "abre o duplex.py")
        self.assertEqual(dev.fix_names("Olha o duplex.py"), "Olha o duplex.py")
        self.assertEqual(dev.fix_names("Roda os testes"), "Roda os testes")


class SettingsBlockTest(unittest.TestCase):
    DENY = ["Bash(curl:*)", "Bash(rm -rf *)", "Read(**/.env)"]
    ASK = ["Bash(git commit *)", "Bash(git push *)", "Bash(git branch *)"]

    def bash(self, command):
        return {"tool_name": "Bash", "tool_input": {"command": command}}

    def test_what_his_settings_forbid_or_want_to_approve_is_told_apart_from_what_is_just_not_allowed(self):
        self.assertEqual(dev.classify(self.bash("curl -sS -i --max-time 15 https://example.com"), self.DENY, self.ASK), "deny")
        self.assertEqual(dev.classify(self.bash("rm -rf build"), self.DENY, self.ASK), "deny")
        self.assertEqual(dev.classify({"tool_name": "Read", "tool_input": {"file_path": "/x/y/.env"}}, self.DENY, self.ASK), "deny")
        self.assertEqual(dev.classify(self.bash("git commit -m x"), self.DENY, self.ASK), "ask")
        self.assertEqual(dev.classify(self.bash("git branch --show-current"), self.DENY, self.ASK), "ask")
        self.assertEqual(dev.classify(self.bash("npm --version"), self.DENY, self.ASK), "open")
        self.assertEqual(dev.classify(self.bash("curlish tool"), self.DENY, self.ASK), "open")  # a prefix is a whole word

    def test_missing_settings_files_are_skipped(self):
        self.assertEqual(dev.settings_rules("deny", files=("/nao/existe.json",)), [])


class SpeakableTest(unittest.TestCase):
    def test_it_stops_where_the_reading_part_starts_and_drops_markdown(self):
        text = ("O `duplex.py` é a base da conversa por voz. Ele não toca em microfone.\n"
                "Eu li o arquivo, mas não rodei nada.\n**Peças**\n- **`StreamingVad`** usa o Silero\n- `Player` toca")
        spoken = dev.speakable(text)
        self.assertEqual(spoken, "O duplex.py é a base da conversa por voz. Ele não toca em microfone. Eu li o arquivo, mas não rodei nada.")
        for mark in ("`", "*", "#", "-"):
            self.assertNotIn(mark, dev.speakable("**Peças** `x` # y"))

    def test_it_keeps_at_most_the_asked_number_of_sentences(self):
        self.assertEqual(dev.speakable("Um. Dois. Três. Quatro.", 2), "Um. Dois.")


class ProgressTest(unittest.TestCase):
    def test_lines_vary_and_never_name_the_tool_or_repeat(self):
        rng = random.Random(1)
        last, seen = None, set()
        for _ in range(30):
            line = dev.progress_line("Read", {"file_path": "/x/duplex.py"}, last, rng)
            self.assertNotEqual(line, last)
            self.assertIn("duplex", line)
            seen.add(line)
            last = line
        self.assertGreater(len(seen), 1)
        for pool in (dev.THINKING, dev.STILL, dev.READING, dev.EDITING, dev.SEARCHING, dev.RUNNING, dev.WEB):
            for line in pool:
                self.assertNotRegex(line.lower(), r"claude|bash|tool|ferramenta|modelo")

    def test_a_tool_not_worth_announcing_is_silent(self):
        self.assertIsNone(dev.progress_line("TodoWrite", {}))
        self.assertIsNotNone(dev.progress_line("Bash", {"command": "ls"}))


class ReplyTest(unittest.TestCase):
    def test_the_part_before_the_separator_is_spoken_and_all_of_it_is_kept(self):
        spoken, full = dev.split_reply("Ajustei o teste, senhor. Falta rodar a suíte.\n---\nArquivos: a.py, b.py")
        self.assertEqual(spoken, "Ajustei o teste, senhor. Falta rodar a suíte.")
        self.assertIn("Arquivos: a.py", full)

    def test_a_long_reply_without_separator_is_cut_at_a_sentence(self):
        text = "Fiz isso. " * 120
        spoken, full = dev.split_reply(text)
        self.assertLessEqual(len(spoken), 700)
        self.assertTrue(spoken.endswith("."))
        self.assertEqual(full, text.strip())


class CommandTest(unittest.TestCase):
    def test_windows_goes_through_wsl_and_the_session_is_resumed(self):
        command = dev.build_command("abc-123", ["Read", "Bash(ls:*)"], windows=True)
        self.assertEqual(command[:2], ["wsl.exe", "-d"])
        self.assertIn("--exec", command)  # no shell in between: the rule parentheses would be a syntax error there
        self.assertNotIn(dev.DEV_BRIEFING, command)  # the instructions travel in a file
        self.assertIn(dev.MIND_DIR, command)
        self.assertEqual(command[command.index("--resume") + 1], "abc-123")
        self.assertEqual(command[command.index("--allowedTools") + 1:], ["Read", "Bash(ls:*)"])
        self.assertEqual(command[command.index("--permission-mode") + 1], "acceptEdits")
        self.assertEqual(command[command.index("--setting-sources") + 1], "user,project")

    def test_linux_runs_it_directly_and_a_new_session_has_no_resume(self):
        command = dev.build_command(None, ["Read"], windows=False)
        self.assertEqual(command[0], dev.CLAUDE)
        self.assertNotIn("--resume", command)


class FakeProc:
    def __init__(self, lines, block=False):
        self._lines, self._block = lines, block
        self.killed = threading.Event()
        self.written = ""
        self.stdin = self
        self.stdout = self._out()

    def write(self, text):
        self.written += text

    def close(self):
        pass

    def _out(self):
        for line in self._lines:
            yield line + "\n"
        if self._block:
            self.killed.wait(5)

    def poll(self):
        return 0 if (self.killed.is_set() or not self._block and not self._lines) else None

    def kill(self):
        self.killed.set()

    def wait(self):
        pass


def event(**kw):
    return json.dumps(kw)


class RunTurnTest(unittest.TestCase):
    def run_it(self, proc, ceiling=None, cancel=None, tools=None):
        seen = []
        result = dev.run_turn("conserta o teste", None, ["Read"], ceiling, lambda n, i: seen.append((n, i)),
                              cancel or threading.Event(), popen=lambda *a, **k: proc, windows=False)
        return result, seen

    def test_tools_are_announced_and_the_result_carries_session_and_denials(self):
        proc = FakeProc([
            event(type="system", subtype="init"),
            event(type="assistant", message={"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/x/a.py"}}]}),
            event(type="result", result="Pronto, senhor.", session_id="s-1", is_error=False,
                  permission_denials=[{"tool_name": "Bash", "tool_input": {"command": "npm install"}}]),
        ])
        result, seen = self.run_it(proc)
        self.assertEqual(seen, [("Read", {"file_path": "/x/a.py"})])
        self.assertEqual((result.text, result.session_id), ("Pronto, senhor.", "s-1"))
        self.assertEqual(result.denials[0]["tool_input"]["command"], "npm install")
        self.assertEqual(proc.written, "conserta o teste")  # the sentence goes through stdin, never the command line

    def test_odd_lines_are_skipped_and_an_error_result_is_reported(self):
        proc = FakeProc(["não é json", event(type="result", result="falhou feio", is_error=True, session_id="s")])
        result, _ = self.run_it(proc)
        self.assertEqual(result.error, "falhou feio")

    def test_the_ceiling_kills_a_turn_that_runs_too_long(self):
        proc = FakeProc([], block=True)
        result, _ = self.run_it(proc, ceiling=0.3)
        self.assertTrue(result.timed_out)
        self.assertTrue(proc.killed.is_set())

    def test_calling_the_jarvis_by_name_cancels_it(self):
        cancel = threading.Event()
        proc = FakeProc([], block=True)
        threading.Timer(0.2, cancel.set).start()
        result, _ = self.run_it(proc, cancel=cancel)
        self.assertTrue(result.cancelled)
        self.assertFalse(result.timed_out)

    def test_a_run_that_prints_no_result_is_an_error_never_silence(self):
        proc = FakeProc(["/bin/bash: -c: line 1: syntax error near unexpected token `('"])
        result, _ = self.run_it(proc)
        self.assertIn("syntax error", result.error)
        self.assertEqual(result.text, "")

    def test_it_never_starts_when_the_binary_is_missing(self):
        def broken(*a, **k):
            raise FileNotFoundError("claude")
        result = dev.run_turn("x", None, [], None, lambda *a: None, threading.Event(), popen=broken, windows=False)
        self.assertIn("não consegui iniciar", result.error)


class TelegramTest(unittest.TestCase):
    def test_send_never_raises(self):
        def broken(*a, **k):
            raise OSError("sem rede")
        self.assertFalse(dev.send_telegram("t", "1", "oi", opener=broken))


if __name__ == "__main__":
    unittest.main()
