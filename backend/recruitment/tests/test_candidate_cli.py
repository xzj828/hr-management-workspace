import subprocess
from unittest.mock import patch

from django.test import SimpleTestCase

from recruitment.rpa.candidates import deep_search_args, parse_candidate_output
from recruitment.rpa.cli import BossCliError, BossCliRunner, CliAccountConfig


RECOMMEND_OUTPUT = """推荐列表（按来源分组）：共 1 人。

常规推荐（1）
  - 1. 林晓｜薪资:20-30K｜信息:北京 / 3年 / 本科｜期望:前端工程师｜经历:星云科技 前端工程师｜可打招呼
    优势: Vue / ToB

打招呼产生的推荐（0）
  - 暂无
"""

SEARCH_OUTPUT = """常规搜索结果（关键词：Vue；当前岗位：前端工程师）
共 1 人

1. 周敏｜刚刚活跃｜北京 5年 本科｜标签:离职-随时到岗/本科
   摘要: 高级前端工程师
   亮点: Vue / TypeScript
   期望职位 前端工程师 北京
   经历: 星云科技 前端
   教育: 海淀大学 本科
"""

DEEP_OUTPUT = """深度搜索：已触发「立即匹配」。
本次新增推荐简历（最新20条）
共 1 人

1. 王宁
   概要：上海 · 6年 · 本科
   经历：远山科技 高级前端工程师
   教育：华东大学 本科
   推荐：有大型 ToB 项目经验
"""


class CandidateParserTests(SimpleTestCase):
    def test_recommend_parser_keeps_structured_fields(self):
        rows = parse_candidate_output(RECOMMEND_OUTPUT, source="recommend")

        self.assertEqual(rows[0]["display_name"], "林晓")
        self.assertEqual(rows[0]["identity_quality"], "fingerprint")
        self.assertEqual(rows[0]["tags"], ["Vue", "ToB"])
        self.assertEqual(rows[0]["city"], "北京")
        self.assertEqual(rows[0]["current_title"], "前端工程师")

    def test_normal_search_parser_reads_summary_and_tags(self):
        rows = parse_candidate_output(SEARCH_OUTPUT, source="search")

        self.assertEqual(rows[0]["display_name"], "周敏")
        self.assertEqual(rows[0]["current_title"], "高级前端工程师")
        self.assertEqual(rows[0]["tags"], ["Vue", "TypeScript"])
        self.assertIn("星云科技", rows[0]["experience"])

    def test_deep_search_parser_reads_latest_matches(self):
        rows = parse_candidate_output(DEEP_OUTPUT, source="deep_search")

        self.assertEqual(rows[0]["display_name"], "王宁")
        self.assertEqual(rows[0]["city"], "上海")
        self.assertEqual(rows[0]["education"], "华东大学 本科")
        self.assertEqual(rows[0]["advantage"], "有大型 ToB 项目经验")

    def test_deep_search_arguments_require_explicit_match(self):
        args = deep_search_args(job="前端", core=["Vue 3"], bonus=["ToB"], match=True)

        self.assertEqual(
            args,
            ["deep-search", "--job", "前端", "--core", "Vue 3", "--bonus", "ToB", "--match"],
        )


class CandidateRunnerTests(SimpleTestCase):
    def setUp(self):
        self.account = CliAccountConfig("C:/Edge/msedge.exe", "C:/profiles/boss", 53470)

    @patch("recruitment.rpa.cli.subprocess.run")
    def test_search_arguments_are_passed_without_shell(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, SEARCH_OUTPUT.encode("utf-8"), b"")

        rows = BossCliRunner(cli_path="C:/tools/boss.exe").search(self.account, "Vue")

        command = run.call_args.args[0]
        self.assertTrue(command[0].lower().endswith("boss.exe"))
        self.assertEqual(command[1:], ["search", "Vue"])
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(rows[0]["display_name"], "周敏")

    @patch.object(BossCliRunner, "_run_chat_bridge")
    @patch("recruitment.rpa.cli.subprocess.run")
    def test_recommend_enriches_aligned_snapshot_with_platform_stable_id(self, run, bridge):
        run.return_value = subprocess.CompletedProcess([], 0, RECOMMEND_OUTPUT.encode("utf-8"), b"")
        bridge.return_value = {
            "ok": True,
            "rows": [{"index": 1, "display_name": "林晓", "external_id": "geek-101"}],
        }

        rows = BossCliRunner(cli_path="C:/tools/boss.exe").recommend(self.account, "前端工程师")

        self.assertEqual(rows[0]["external_id"], "geek-101")
        bridge.assert_called_once_with(
            self.account,
            "candidate_list",
            {"source": "recommend"},
            timeout_seconds=45,
        )

    @patch.object(BossCliRunner, "_run_chat_bridge")
    @patch("recruitment.rpa.cli.subprocess.run")
    def test_candidate_enrichment_refuses_misaligned_browser_snapshot(self, run, bridge):
        run.return_value = subprocess.CompletedProcess([], 0, RECOMMEND_OUTPUT.encode("utf-8"), b"")
        bridge.return_value = {
            "ok": True,
            "rows": [{"index": 1, "display_name": "同名但不同目标", "external_id": "geek-101"}],
        }

        rows = BossCliRunner(cli_path="C:/tools/boss.exe").recommend(self.account, "前端工程师")

        self.assertEqual(rows[0]["external_id"], "")

    def test_runner_rejects_control_characters(self):
        runner = BossCliRunner(cli_path="C:/tools/boss.exe")

        with self.assertRaisesMessage(BossCliError, "参数包含非法字符"):
            runner.search(self.account, "Vue\npositions")

    def test_deep_search_does_not_match_without_explicit_flag(self):
        self.assertNotIn("--match", deep_search_args(job="前端", core=[], bonus=[], match=False))
