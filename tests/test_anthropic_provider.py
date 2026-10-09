import importlib.util
import unittest
from types import SimpleNamespace

from jarvis.actions import TOOLS
from jarvis.talker.base import to_anthropic_tools

HAS_SDK = importlib.util.find_spec("anthropic") is not None
USAGE = SimpleNamespace(input_tokens=30, output_tokens=8)


class ConversionTest(unittest.TestCase):
    def test_every_real_tool_converts(self):
        converted = to_anthropic_tools(TOOLS)
        self.assertEqual([t["name"] for t in converted], [x["function"]["name"] for x in TOOLS])
        for tool in converted:
            self.assertEqual(set(tool), {"name", "description", "input_schema"})
            self.assertEqual(tool["input_schema"]["type"], "object")

    def test_nothing_to_convert(self):
        self.assertEqual(to_anthropic_tools(None), [])


@unittest.skipUnless(HAS_SDK, "anthropic not installed")
class AnthropicTalkerTest(unittest.TestCase):
    def make(self, content):
        from jarvis.talker.anthropic_provider import AnthropicTalker

        talker = AnthropicTalker.__new__(AnthropicTalker)
        talker._model, talker._max_tokens = "m", 400
        talker.sent = {}

        def create(**kwargs):
            talker.sent = kwargs
            return SimpleNamespace(content=content, usage=USAGE)

        talker._client = SimpleNamespace(messages=SimpleNamespace(create=create))
        return talker

    MSGS = [{"role": "user", "content": "oi"}]

    def test_tool_use_block_becomes_a_tool_call_and_tools_are_sent(self):
        t = self.make([SimpleNamespace(type="tool_use", name="anotar", input={"texto": "pão"})])
        reply = t.reply("sys", self.MSGS, tools=TOOLS)
        self.assertEqual((reply.text, reply.tool_call.name, reply.tool_call.arguments), ("", "anotar", {"texto": "pão"}))
        self.assertEqual(len(t.sent["tools"]), len(TOOLS))
        self.assertNotIn("indisponíveis", t.sent["system"])

    def test_plain_text_still_works_and_sends_no_tools_when_none_offered(self):
        t = self.make([SimpleNamespace(type="text", text=" Às ordens, senhor. ")])
        reply = t.reply("sys", self.MSGS)
        self.assertEqual((reply.text, reply.tool_call), ("Às ordens, senhor.", None))
        self.assertNotIn("tools", t.sent)


if __name__ == "__main__":
    unittest.main()
