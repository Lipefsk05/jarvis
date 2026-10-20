import unittest
from datetime import date
from email.message import EmailMessage

from jarvis import mail as m


def raw(subject="Fatura", sender="Banco <no-reply@banco.com>", body="Sua fatura vence amanhã.", html=None):
    msg = EmailMessage()
    msg["From"], msg["Subject"], msg["Date"] = sender, subject, "Tue, 20 Oct 2026 09:00:00 -0300"
    if html:
        msg.set_content(html, subtype="html")
    else:
        msg.set_content(body)
    return msg.as_bytes()


class FakeImap:
    """Records every command so tests can prove the mailbox is only read."""
    def __init__(self, messages, size=1000):
        self.messages, self.size, self.calls = messages, size, []

    def login(self, user, password):
        self.calls.append(("login", user))

    def select(self, box, readonly=False):
        self.calls.append(("select", box, readonly))
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        self.calls.append(("search",) + criteria)
        return "OK", [b" ".join(str(i + 1).encode() for i in range(len(self.messages)))]

    def fetch(self, uid, spec):
        self.calls.append(("fetch", spec))
        if "RFC822.SIZE" in spec:
            return "OK", [b"%s (RFC822.SIZE %d)" % (uid, self.size)]
        return "OK", [(b"%s (BODY[] {1})" % uid, self.messages[int(uid) - 1]), b")"]

    def logout(self):
        self.calls.append(("logout",))


ACCOUNT = m.MailAccount("profissional", "eu@gmail.com", "senha")


class MailTest(unittest.TestCase):
    def test_reads_sender_subject_and_snippet(self):
        fake = FakeImap([raw()])
        mails = m.fetch_recent(ACCOUNT, date(2026, 10, 19), connect=lambda host: fake)
        self.assertEqual(mails[0].sender, "Banco")
        self.assertEqual(mails[0].subject, "Fatura")
        self.assertIn("fatura vence", mails[0].snippet)

    def test_only_reads_the_mailbox(self):
        fake = FakeImap([raw()])
        m.fetch_recent(ACCOUNT, date(2026, 10, 19), connect=lambda host: fake)
        self.assertIn(("select", "INBOX", True), fake.calls)
        self.assertEqual(fake.calls[-1], ("logout",))
        for call in fake.calls:
            self.assertIn(call[0], {"login", "select", "search", "fetch", "logout"})
            if call[0] == "fetch":
                self.assertTrue("BODY.PEEK" in call[1] or "RFC822.SIZE" in call[1])  # PEEK never marks as read
        self.assertIn(("search", "SINCE", "19-Oct-2026"), fake.calls)

    def test_big_messages_come_by_header_only(self):
        fake = FakeImap([raw()], size=m.MAX_SIZE_BYTES + 1)
        mails = m.fetch_recent(ACCOUNT, date(2026, 10, 19), connect=lambda host: fake)
        self.assertEqual(mails[0].snippet, "")
        self.assertTrue(any("HEADER.FIELDS" in c[1] for c in fake.calls if c[0] == "fetch" and "SIZE" not in c[1]))

    def test_html_only_mail_loses_tags_and_scripts(self):
        mail = m.to_mail(raw(html="<style>x{}</style><p>Olá <b>mundo</b></p><script>alert(1)</script>"))
        self.assertEqual(mail.snippet, "Olá mundo")

    def test_snippet_is_capped_and_encoded_subject_decoded(self):
        mail = m.to_mail(raw(subject="=?utf-8?q?Reuni=C3=A3o_amanh=C3=A3?=", body="a " * 1000))
        self.assertEqual(mail.subject, "Reunião amanhã")
        self.assertLessEqual(len(mail.snippet), m.SNIPPET_CHARS)

    def test_limit_keeps_the_newest(self):
        fake = FakeImap([raw(subject=f"m{i}") for i in range(10)])
        mails = m.fetch_recent(ACCOUNT, date(2026, 10, 19), limit=3, connect=lambda host: fake)
        self.assertEqual([x.subject for x in mails], ["m7", "m8", "m9"])

    def test_logs_out_even_when_login_fails(self):
        class Bad(FakeImap):
            def login(self, user, password):
                raise OSError("down")
        fake = Bad([])
        with self.assertRaises(OSError):
            m.fetch_recent(ACCOUNT, date(2026, 10, 19), connect=lambda host: fake)
        self.assertEqual(fake.calls, [("logout",)])


class AccountsTest(unittest.TestCase):
    def test_parses_pairs_and_strips_spaces_of_the_app_password(self):
        accounts = m.parse_accounts({
            "JARVIS_IMAP_PROFISSIONAL_USER": "a@gmail.com", "JARVIS_IMAP_PROFISSIONAL_PASSWORD": "abcd efgh ijkl mnop",
            "JARVIS_IMAP_CAFE_USER": "b@cafelabs.net",  # no password: skipped
        })
        self.assertEqual(len(accounts), 1)
        self.assertEqual((accounts[0].name, accounts[0].password), ("profissional", "abcdefghijklmnop"))

    def test_password_never_shows_in_repr(self):
        self.assertNotIn("senha", repr(ACCOUNT))


if __name__ == "__main__":
    unittest.main()
