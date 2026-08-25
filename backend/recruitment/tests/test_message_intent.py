from django.test import SimpleTestCase

from recruitment.services.message_intent import MessageIntent, classify_candidate_message


class MessageIntentTests(SimpleTestCase):
    def test_resume_and_rejection_have_highest_priority(self):
        self.assertEqual(
            classify_candidate_message("我把简历发过来了", has_resume_attachment=True),
            MessageIntent.RESUME_RECEIVED,
        )
        self.assertEqual(classify_candidate_message("谢谢，我暂时不考虑了"), MessageIntent.REJECTED)

    def test_only_explicit_observation_or_learning_goes_to_hr(self):
        for text in ("我想先了解一下公司", "想再了解一下这个岗位", "我先考虑看看"):
            self.assertEqual(classify_candidate_message(text), MessageIntent.OBSERVING)

        for text in ("你好", "在吗", "薪资多少", "我对岗位有兴趣"):
            self.assertEqual(classify_candidate_message(text), MessageIntent.REQUEST_RESUME)

    def test_empty_and_non_candidate_content_do_not_trigger_actions(self):
        self.assertEqual(classify_candidate_message("   "), MessageIntent.IGNORE)
