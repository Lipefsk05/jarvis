import tempfile
import threading
import unittest
from pathlib import Path

from jarvis.conversation import History


class HistoryThreadSafetyTest(unittest.TestCase):
    """A reply (worker thread) and the reminder scheduler (event loop) write to the same history."""

    def test_many_threads_writing_at_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = History(max_messages=20, path=Path(tmp) / "conversa.json")
            errors = []

            def worker(role):
                try:
                    for i in range(300):
                        history.add(1, role, f"{role} {i}")
                        history.messages(1)
                        if i % 50 == 0:
                            history.drop_last(1)
                except Exception as exc:  # noqa: BLE001 - the test is about not raising
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(role,)) for role in ("user", "assistant", "user", "assistant")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            messages = history.messages(1)
            self.assertLessEqual(len(messages), 20)
            self.assertTrue(not messages or messages[0]["role"] == "user")  # still starts with a user message
            self.assertEqual(History(20, Path(tmp) / "conversa.json").messages(1), messages)  # and the file is intact


if __name__ == "__main__":
    unittest.main()
