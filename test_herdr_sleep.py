"""Tests for herdr-sleep's decisions. Run: python3 -m unittest test_herdr_sleep (from this folder)."""
import json
import os
import tempfile
import time
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

hs = SourceFileLoader("herdr_sleep", str(Path(__file__).with_name("herdr-sleep"))).load_module()

SID = "11111111-2222-4333-8444-555555555555"
RULE = "\x1b[0m\x1b[38;2;136;136;136m" + "─" * 40 + "\x1b[0m"
FOOTER = "  \x1b[0m\x1b[38;2;153;153;153m[Opus 5.5] 15% | $2.77\x1b[0m"


def composer(line):
    return "\n".join(["some reply", "", RULE, line, RULE, FOOTER])


class Config(unittest.TestCase):
    def read(self, text):
        saved = hs.CONFIG_PATH
        with tempfile.TemporaryDirectory() as tmp:
            hs.CONFIG_PATH = Path(tmp) / "config.json"
            if text is not None:
                hs.CONFIG_PATH.write_text(text)
            try:
                return hs.read_config()
            finally:
                hs.CONFIG_PATH = saved

    def test_good_missing_and_bad_files(self):
        self.assertEqual(self.read(None), ({}, None))
        self.assertEqual(self.read('{"idle_hours": 12, "exclude_cwds": ["~/x"]}')[0]["idle_hours"], 12)
        for bad in ('{"idle_hours": "12"}', '{"exclude_cwds": [1]}', '{"typo": 1}', '{"idle_hours": true}', "[]", "{"):
            self.assertIsNotNone(self.read(bad)[1], bad)  # sleeping turns off rather than ignoring the file


class ReplayArgv(unittest.TestCase):
    def test_keeps_launch_flags_and_drops_session_selection(self):
        argv = ["claude", "--allow-dangerously-skip-permissions", "--resume", "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
                "--effort", "max", "--model=sonnet", "--allowed-tools", "Read", "mcp__x__y", "--permission-mode", "auto", "-c"]
        self.assertEqual(hs.replay_argv(argv), (["claude", "--allow-dangerously-skip-permissions", "--effort", "max",
                                                 "--model=sonnet", "--allowed-tools", "Read", "mcp__x__y",
                                                 "--permission-mode", "auto"], None))

    def test_refuses_what_cannot_be_replayed(self):
        for argv in (["claude", "fix the bug"], ["claude", "-p", "x"], ["claude", "--fork-session"],
                     ["claude", "--weird-new-flag"], ["claude", "--", "x"], ["claude", "--model"], None):
            self.assertIsNone(hs.replay_argv(argv)[0], argv)


class PermissionMode(unittest.TestCase):
    def test_resumes_in_the_mode_before_sleep(self):
        allow = ["claude", "--allow-dangerously-skip-permissions"]
        self.assertEqual(hs.with_mode(allow + ["--permission-mode", "auto", "--effort", "max"], "bypassPermissions"),
                         allow + ["--effort", "max", "--permission-mode", "bypassPermissions"])
        self.assertEqual(hs.with_mode(allow, "default"), allow + ["--permission-mode", "manual"])
        self.assertEqual(hs.with_mode(["claude"], "bypassPermissions"), ["claude"])  # Claude would refuse bypass
        self.assertEqual(hs.with_mode(allow, ""), allow)
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write('{"type":"permission-mode","permissionMode":"auto"}\n'
                    '{"type":"user","permissionMode":"bypassPermissions"}\n{"type":"x"}\n')
        self.assertEqual(hs.last_permission_mode(Path(f.name)), "bypassPermissions")
        os.unlink(f.name)

    def test_reads_the_live_mode_from_the_footer(self):
        bypass = "  \x1b[0m\x1b[38;2;255;107;128m⏵⏵ bypass permissions on\x1b[0m (shift+tab to cycle) · ← 5 agents"
        self.assertEqual(hs.screen_mode(composer("❯\xa0") + "\n" + bypass), "bypassPermissions")
        self.assertEqual(hs.screen_mode(composer("❯\xa0") + "\n  ⏸ manual mode on · ← 5 agents"), "default")
        self.assertEqual(hs.screen_mode("auto mode on\n" + composer("❯\xa0")), "")  # text above the composer


class Composer(unittest.TestCase):
    def test_states(self):
        self.assertEqual(hs.composer_state(composer("❯\xa0")), "empty")
        self.assertEqual(hs.composer_state(composer("❯\xa0\x1b[0m\x1b[2mперевірив пошту, все ок\x1b[0m")), "empty")
        self.assertEqual(hs.composer_state(composer("❯\xa0зроби ще одне")), "draft")
        self.assertEqual(hs.composer_state("\n".join([RULE, "❯\xa0перший рядок", "другий рядок", RULE])), "draft")
        self.assertEqual(hs.composer_state("❯ no frame"), "unknown")
        self.assertEqual(hs.composer_state(None), "unknown")


class Children(unittest.TestCase):
    def test_servers_are_fine_background_commands_are_not(self):
        procs = {10: (1, "claude"), 11: (10, "npm exec chrome-devtools-mcp@latest"), 12: (10, "pond mcp"),
                 13: (10, "/usr/bin/clangd --background-index"), 14: (10, "<defunct>"), 99: (1, "unrelated")}
        self.assertEqual(hs.busy_children(10, procs), [])
        procs[15] = (10, "/bin/zsh -c source /Users/x/.claude/shell-snapshots/snapshot-zsh-1.sh && eval 'mcp run'")
        procs[16] = (10, "caffeinate -i -t 300")
        procs[17] = (10, "npm run dev")
        self.assertEqual(len(hs.busy_children(10, procs)), 2)


class Transcript(unittest.TestCase):
    def test_messages_and_recap(self):
        rows = [{"type": "user", "message": {"content": "перенеси сервер"}},
                {"type": "user", "isMeta": True, "message": {"content": "meta"}},
                {"type": "user", "message": {"content": "<command-name>/model</command-name>"}},
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"},
                                                              {"type": "text", "text": "План готовий."}]}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
                {"type": "system", "subtype": "away_summary", "content": "Мета — перенос. (disable recaps in /config)"}]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\nnot json\n")
        path = Path(f.name)
        self.assertEqual(hs.messages(path), [("user", "перенеси сервер"), ("assistant", "План готовий.")])
        self.assertEqual(hs.last_recap(path), "Мета — перенос.")
        path.unlink()


class Page(unittest.TestCase):
    def test_last_actions_read_at_a_glance(self):
        def tool(name, **inp):
            return {"type": "tool_use", "name": name, "input": inp}
        rows = [("user", "зроби план"),
                ("user", "This session is being continued from a previous conversation"),  # compaction, flagged below
                ("assistant", [tool("Read", file_path="/r/PLAN.md"), tool("Grep", pattern="TODO", path="/r/src")]),
                ("user", [{"type": "tool_result", "content": "ok"}]),
                ("assistant", [tool("Edit", file_path="/r/PLAN.md"), tool("Edit", file_path="/r/PLAN.md"),
                               tool("ToolSearch", query="x"), tool("Write", file_path="/r/BUILD.md")]),
                ("assistant", [tool("Bash", description="Run tests", command="pytest")] * 2),
                ("assistant", [tool("AskUserQuestion", questions=[{"question": "Ставимо?"}])])]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            for i, (role, content) in enumerate(rows):
                f.write(json.dumps({"type": role, "timestamp": f"2026-11-05T17:{10 + i}:00.000Z",
                                    "isCompactSummary": i == 1, "message": {"content": content}}) + "\n")
        acts = hs.recent_actions(Path(f.name), "/r")
        os.unlink(f.name)
        self.assertEqual([(a["kind"], a["targets"], a["n"]) for a in acts],
                         [("you", ["ти: «зроби план»"], 1), ("read", ["PLAN.md", "src"], 1), ("edit", ["PLAN.md"], 1),
                          ("write", ["BUILD.md"], 1), ("bash", ["Run tests"], 2), ("ask", ["питання тобі: Ставимо?"], 1)])

    def test_project_material_reads_the_brief_and_project_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = os.path.realpath(tmp)
            briefs, project, other = (Path(tmp) / d for d in ("briefs", "repo", "elsewhere"))
            for d in (briefs, project, other):
                d.mkdir()
            (briefs / "b.md").write_text("Запит: зроби сайт")
            (other / "secret.md").write_text("не для Haiku")
            (project / "CLAUDE.md").write_text("Сайт спільноти")
            saved, hs.BRIEF_DIRS = hs.BRIEF_DIRS, [str(briefs)]
            try:
                text = hs.project_material([("user", f"Прочитай {other}/secret.md і бриф {briefs}/b.md")], str(project))
                self.assertIn("зроби сайт", text)
                self.assertIn("Сайт спільноти", text)
                self.assertNotIn("не для Haiku", text)
                self.assertIn("Перше повідомлення", hs.project_material([("user", "просто текст")], str(project)))
            finally:
                hs.BRIEF_DIRS = saved

    def test_page_fits_the_pane_and_keeps_the_actions(self):
        rec = {"name": "owner", "slept_at": "09.11 13:39", "cwd": "/r", "argv": ["claude"],
               "place": "Personal / Site", "project": "Проєкт " * 40,
               "summary": "речення " * 60, "last_user": "текст " * 80, "last_assistant": "рядок\n" * 40}
        acts = [{"when": hs.datetime(2026, 11, 5, 17, i), "kind": "bash", "sym": "▸", "targets": [f"step {i}"], "n": 1}
                for i in range(8)]
        for rows in (24, 40):
            lines = hs.page_lines(rec, SID, acts, 100, rows)
            used = sum(len(hs.ANSI.sub("", ln)) // 100 + 1 for ln in lines) + 1
            self.assertLessEqual(used, rows)
            self.assertTrue(any("step 7" in ln for ln in lines) and any("step 0" in ln for ln in lines))
        small = hs.page_lines(rec, SID, acts, 100, 24)
        self.assertFalse(any("Остання відповідь" in ln for ln in small))
        self.assertTrue(any("Проєкт" in ln and "Personal / Site" in ln for ln in hs.page_lines(rec, SID, acts, 100, 40)))


class WhyAwake(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.path.realpath(self.tmp.name)
        project = Path(self.tmp.name) / "projects" / hs.project_dir_name(self.cwd)
        project.mkdir(parents=True)
        self.path = project / f"{SID}.jsonl"
        self.write_turn(hours_ago=30)
        self.saved = {k: getattr(hs, k) for k in ("PROJECTS", "herdr", "ps_table", "screen", "tree_rss_mb")}
        hs.PROJECTS = Path(self.tmp.name) / "projects"
        self.screen = composer("❯\xa0")
        self.procs = {50: (1, "-zsh"), 100: (50, "claude --allow-dangerously-skip-permissions"),
                      101: (100, "npm exec @playwright/mcp@latest")}
        hs.herdr = lambda *a, **k: {"process_info": {"foreground_processes": [
            {"pid": 100, "argv": ["claude", "--allow-dangerously-skip-permissions", "--effort", "max"]},
            {"pid": 101, "argv": None}]}}
        hs.ps_table = lambda: self.procs
        hs.screen = lambda pane: self.screen
        hs.tree_rss_mb = lambda pid, procs: 400
        self.agent = {"pane_id": "w8:p2", "tab_id": "w8:t2", "agent": "claude", "agent_status": "idle",
                      "focused": False, "foreground_cwd": self.cwd, "agent_session": {"value": SID}}

    def write_turn(self, hours_ago):
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - hours_ago * 3600))
        bookkeeping = {"type": "artifact-autoreact-ledger", "sessionId": SID}  # written later, must not count
        self.path.write_text(json.dumps({"type": "user", "timestamp": stamp, "message": {"content": "x"}},
                                        separators=(",", ":")) + "\n" + json.dumps(bookkeeping) + "\n")

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(hs, k, v)
        self.tmp.cleanup()

    def why(self, agents=None, tabs=None, manual=False):
        return hs.why_awake(self.agent, agents or [self.agent], tabs or {}, manual)[0]

    def test_sleeps_a_quiet_claude_with_its_flags(self):
        reason, facts = hs.why_awake(self.agent, [self.agent], {})
        self.assertIsNone(reason)
        self.assertEqual(facts["argv"], ["claude", "--allow-dangerously-skip-permissions", "--effort", "max"])
        self.assertEqual(facts["pid"], 100)

    def test_stays_awake(self):
        self.assertEqual(self.why(tabs={"w8:t2": {"focused": True}}), "focused")
        self.write_turn(hours_ago=2)
        self.assertEqual(self.why(), "quiet 2.0 h")
        self.assertIsNone(self.why(manual=True))  # sleep-pane skips the quiet time
        self.path.write_text('{"type":"artifact-autoreact-ledger"}\n')
        self.assertEqual(self.why(), "no conversation turns yet")
        self.write_turn(hours_ago=30)
        self.agent["agent_status"] = "working"
        self.assertEqual(self.why(), "status working")
        self.agent["agent_status"] = "done"
        self.assertEqual(self.why(agents=[self.agent, dict(self.agent, pane_id="w9:p1")]), "session open in another pane")
        self.screen = composer("❯\xa0не надіслано")
        self.assertEqual(self.why(), "composer draft")
        self.screen = composer("❯\xa0")
        self.procs[102] = (100, "/bin/zsh -c source ~/.claude/shell-snapshots/s.sh && sleep 999")
        self.assertTrue(self.why().startswith("background command"))
        del self.procs[102]
        self.procs[50] = (1, "/opt/herdr/herdr server")
        self.assertEqual(self.why(), "claude is not a child of the pane shell")
        self.procs[50] = (1, "-zsh")
        self.assertIsNone(self.why())
        hs.EXCLUDE_CWDS.add(self.cwd)
        try:
            self.assertEqual(self.why(), "excluded")
        finally:
            hs.EXCLUDE_CWDS.discard(self.cwd)


if __name__ == "__main__":
    unittest.main()
