from django.test import SimpleTestCase

from recruitment.rpa.conversations import parse_conversation_list


class ConversationSyncParserTests(SimpleTestCase):
    def test_parses_numbered_conversations_and_unread_state(self):
        rows = parse_conversation_list("1. 林然｜产品经理｜未读 2\n2. 周青｜测试工程师｜已读")
        self.assertEqual(rows[0], {"index": 1, "name": "林然", "unread": True})
        self.assertEqual(rows[1], {"index": 2, "name": "周青", "unread": False})

    def test_ignores_diagnostic_lines(self):
        self.assertEqual(parse_conversation_list("正在连接浏览器...\n暂无沟通记录"), [])

