from django.test import SimpleTestCase

from recruitment.rpa.conversations import parse_chat_messages, parse_conversation_list


class ConversationSyncParserTests(SimpleTestCase):
    def test_parses_numbered_conversations_and_unread_state(self):
        rows = parse_conversation_list("1. 林然｜产品经理｜未读 2\n2. 周青｜测试工程师｜已读")
        self.assertEqual(rows[0], {"index": 1, "name": "林然", "unread": True})
        self.assertEqual(rows[1], {"index": 2, "name": "周青", "unread": False})

    def test_ignores_diagnostic_lines(self):
        self.assertEqual(parse_conversation_list("正在连接浏览器...\n暂无沟通记录"), [])

    def test_parses_every_rendered_chat_message_in_order(self):
        output = """成功进入候选人聊天：林然
简历获取状态: 已获取

完整聊天消息：

[candidate] 2026-08-25 09:00 你好
[you] 2026-08-25 09:01 您好
[candidate] 2026-08-25 09:02 这是我的简历
[system] 候选人已发送附件简历
"""

        messages = parse_chat_messages(output)

        self.assertEqual([item["direction"] for item in messages], ["candidate", "hr", "candidate", "system"])
        self.assertEqual(messages[0]["content"], "你好")
        self.assertEqual(messages[2]["content"], "这是我的简历")
        self.assertEqual(messages[0]["sent_at"], "2026-08-25T09:00:00")

