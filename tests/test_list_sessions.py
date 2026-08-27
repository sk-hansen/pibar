import importlib.machinery
import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
LOADER = importlib.machinery.SourceFileLoader(
    "session_browser_list_sessions", str(PLUGIN_ROOT / "list-sessions"))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
SESSIONS = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(SESSIONS)


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        SESSIONS.HOME = str(self.home)

    def tearDown(self):
        self.temp.cleanup()

    def write_json(self, relative, data):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def write_text(self, relative, text):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_jsonl(self, relative, records):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )
        return path

    def test_codex_keeps_user_threads_and_excludes_subagents(self):
        parent_id = "11111111-1111-4111-8111-111111111111"
        child_id = "22222222-2222-4222-8222-222222222222"
        root = Path(".codex/sessions/2026/08/27")
        self.write_jsonl(
            root / f"rollout-2026-08-27T10-00-00-{parent_id}.jsonl",
            [
                {
                    "type": "session_meta",
                    "payload": {
                        "id": parent_id,
                        "cwd": str(self.home / "project"),
                        "thread_source": "user",
                        "source": "cli",
                        "parent_thread_id": None,
                    },
                },
                {
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "Main task"},
                },
            ],
        )
        self.write_jsonl(
            root / f"rollout-2026-08-27T10-01-00-{child_id}.jsonl",
            [
                {
                    "type": "session_meta",
                    "payload": {
                        "id": child_id,
                        "cwd": str(self.home / "project"),
                        "thread_source": "subagent",
                        "source": {"subagent": {"thread_spawn": {}}},
                        "parent_thread_id": parent_id,
                    },
                },
                {
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "Delegated task"},
                },
            ],
        )

        rows = list(SESSIONS.scan_codex())
        self.assertEqual([row["id"] for row in rows], [parent_id])
        self.assertEqual(rows[0]["title"], "Main task")

    def test_claude_only_scans_top_level_conversations(self):
        session_id = "33333333-3333-4333-8333-333333333333"
        project = Path(".claude/projects/-tmp-project")
        self.write_jsonl(
            project / f"{session_id}.jsonl",
            [{
                "type": "user",
                "isSidechain": False,
                "cwd": str(self.home / "project"),
                "message": {"content": "Main Claude task"},
            }],
        )
        self.write_jsonl(
            project / session_id / "subagents/agent-child.jsonl",
            [{
                "type": "user",
                "isSidechain": True,
                "agentId": "child",
                "message": {"content": "Nested child"},
            }],
        )
        self.write_jsonl(
            project / "agent-defensive.jsonl",
            [{
                "type": "user",
                "isSidechain": True,
                "agentId": "defensive",
                "message": {"content": "Flat child"},
            }],
        )

        rows = list(SESSIONS.scan_claude())
        self.assertEqual([row["id"] for row in rows], [session_id])

    def test_opencode_only_selects_rows_without_a_parent(self):
        db = self.home / ".local/share/opencode/opencode.db"
        db.parent.mkdir(parents=True)
        con = sqlite3.connect(db)
        con.execute(
            "create table session ("
            "id text primary key, project_id text, workspace_id text, parent_id text, "
            "directory text, title text, time_updated integer, time_created integer, "
            "model text, agent text, cost real, tokens_input integer, "
            "tokens_output integer, tokens_reasoning integer, slug text)"
        )
        row = (
            "ses_parent", "project", None, None, str(self.home), "Parent", 2000,
            1000, '{"id":"model"}', "build", 0.0, 10, 5, 0, "parent",
        )
        con.execute("insert into session values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
        child = list(row)
        child[0], child[3], child[5], child[6] = "ses_child", "ses_parent", "Child", 3000
        con.execute("insert into session values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", child)
        con.commit()
        con.close()

        rows = list(SESSIONS.scan_opencode())
        self.assertEqual([item["id"] for item in rows], ["ses_parent"])

    def test_copilot_reads_modern_and_legacy_top_level_sessions(self):
        modern_id = "44444444-4444-4444-8444-444444444444"
        child_id = "55555555-5555-4555-8555-555555555555"
        modern = Path(".copilot/session-state")
        self.write_jsonl(
            modern / modern_id / "events.jsonl",
            [
                {
                    "type": "session.start",
                    "data": {
                        "sessionId": modern_id,
                        "context": {"cwd": str(self.home / "modern-project")},
                    },
                    "parentId": None,
                },
                {"type": "subagent.started", "data": {"agentId": "worker"}},
                {"type": "user.message", "data": {"content": "Modern task"}},
            ],
        )
        self.write_jsonl(
            modern / child_id / "events.jsonl",
            [{
                "type": "session.start",
                "data": {
                    "sessionId": child_id,
                    "kind": "subagent",
                    "parentSessionId": modern_id,
                    "context": {"cwd": str(self.home / "modern-project")},
                },
            }],
        )
        self.write_json(
            ".copilot/history-session-state/legacy.json",
            {"summary": "Legacy task", "cwd": str(self.home / "legacy-project")},
        )
        self.write_json(
            ".copilot/history-session-state/legacy-child.json",
            {"summary": "Legacy child", "kind": "subagent"},
        )

        rows = list(SESSIONS.scan_copilot())
        self.assertEqual({row["id"] for row in rows}, {modern_id, "legacy"})
        self.assertEqual(next(row for row in rows if row["id"] == modern_id)["title"],
                         "Modern task")

    def test_pi_keeps_user_forks_but_skips_explicit_subagents(self):
        root = Path(".pi/agent/sessions/--tmp-project--")
        parent = self.write_jsonl(
            root / "parent.jsonl",
            [
                {"type": "session", "id": "parent", "cwd": str(self.home)},
                {"type": "message", "message": {"role": "user", "content": "Parent"}},
            ],
        )
        fork = self.write_jsonl(
            root / "fork.jsonl",
            [
                {
                    "type": "session",
                    "id": "fork",
                    "cwd": str(self.home),
                    "parentSession": str(parent),
                },
                {"type": "message", "message": {"role": "user", "content": "Fork"}},
            ],
        )
        self.write_jsonl(
            root / "child.jsonl",
            [{"type": "session", "id": "child", "kind": "subagent"}],
        )

        rows = list(SESSIONS.scan_pi())
        self.assertEqual({Path(row["id"]).name for row in rows},
                         {parent.name, fork.name})

    def test_gemini_reads_json_and_jsonl_without_nested_children(self):
        project_root = self.home / "gemini-project"
        project_root.mkdir()
        project = Path(".gemini/tmp/gemini-project")
        self.write_text(project / ".project_root", str(project_root))
        chats = project / "chats"
        main_id = "66666666-6666-4666-8666-666666666666"
        legacy_id = "77777777-7777-4777-8777-777777777777"
        self.write_jsonl(
            chats / "session-2026-08-27T10-00-main.jsonl",
            [
                {
                    "sessionId": main_id,
                    "projectHash": "hash",
                    "kind": "main",
                    "startTime": "2026-08-27T10:00:00Z",
                },
                {"id": "message-1", "type": "user", "content": "Gemini task"},
            ],
        )
        self.write_jsonl(
            chats / main_id / "agent-child.jsonl",
            [{"sessionId": "child", "projectHash": "hash", "kind": "subagent"}],
        )
        self.write_jsonl(
            chats / "session-defensive-child.jsonl",
            [{"sessionId": "flat-child", "projectHash": "hash", "kind": "subagent"}],
        )
        self.write_json(
            chats / "session-legacy.json",
            {
                "sessionId": legacy_id,
                "projectHash": "hash",
                "kind": "main",
                "messages": [{"role": "user", "content": "Legacy Gemini task"}],
            },
        )

        rows = list(SESSIONS.scan_gemini())
        self.assertEqual({row["id"] for row in rows}, {main_id, legacy_id})
        self.assertTrue(all(row["dir"] == str(project_root) for row in rows))

    def test_grok_keeps_user_forks_and_excludes_subagent_sessions(self):
        parent_id = "99999999-9999-4999-8999-999999999999"
        fork_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        child_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        legacy_child_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        sessions = Path(".grok/sessions/%2Ftmp%2Fproject")

        def summary(sid, title, **extra):
            return {
                "info": {"id": sid, "cwd": str(self.home / "project")},
                "generated_title": title,
                "created_at": "2026-08-27T10:00:00Z",
                "updated_at": "2026-08-27T10:05:00Z",
                "num_chat_messages": 8,
                "current_model_id": "grok-code-fast-1",
                **extra,
            }

        self.write_json(sessions / parent_id / "summary.json",
                        summary(parent_id, "Main Grok task"))
        self.write_json(
            sessions / fork_id / "summary.json",
            summary(fork_id, "User fork", session_kind="fork",
                    parent_session_id=parent_id),
        )
        self.write_json(
            sessions / child_id / "summary.json",
            summary(child_id, "Delegated task", session_kind="subagent"),
        )
        self.write_json(
            sessions / legacy_child_id / "summary.json",
            summary(legacy_child_id, "Legacy delegated task"),
        )
        self.write_json(
            sessions / parent_id / "subagents" / legacy_child_id / "meta.json",
            {"child_session_id": legacy_child_id},
        )

        with mock.patch.dict(
            os.environ, {"GROK_HOME": str(self.home / ".grok")}
        ):
            rows = list(SESSIONS.scan_grok())

        self.assertEqual({row["id"] for row in rows}, {parent_id, fork_id})
        self.assertEqual(next(row for row in rows if row["id"] == parent_id)["title"],
                         "Main Grok task")
        self.assertIn("grok-code-fast-1", rows[0]["meta"])

    def test_resume_targets_the_selected_sessions(self):
        old_find = SESSIONS.find
        old_open_terminal = SESSIONS.open_terminal
        commands = []
        SESSIONS.find = lambda _agent, _sid: {"dir": str(self.home)}
        SESSIONS.open_terminal = commands.append
        try:
            SESSIONS.resume("opencode", "ses_selected")
            SESSIONS.resume("gemini", "88888888-8888-4888-8888-888888888888")
            SESSIONS.resume("grok", "dddddddd-dddd-4ddd-8ddd-dddddddddddd")
        finally:
            SESSIONS.find = old_find
            SESSIONS.open_terminal = old_open_terminal

        self.assertIn("opencode --session 'ses_selected'", commands[0])
        self.assertIn(
            "gemini --resume '88888888-8888-4888-8888-888888888888'",
            commands[1],
        )
        self.assertIn(
            "grok --resume 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'",
            commands[2],
        )


if __name__ == "__main__":
    unittest.main()
