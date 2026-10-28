#!/usr/bin/env python3
"""以合成資料檢查隔離環境與命令日誌去敏，不讀正式設定、不連外。"""

import argparse
import ast
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import importlib.util
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location(
    "verify_instance_under_test", Path(__file__).with_name("instance.py"),
)
instance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(instance)

SYNTHETIC_URL = (
    "postgresql+psycopg://helper_user:fake%40pass%3A123@market.invalid:5432/"
    "synthetic?options=-csearch_path%3Dmarket"
)
SYNTHETIC_PASSWORD = "fake@pass:123"
ERROR_PREFIX = 'psycopg.ProgrammingError: missing "=" after '
EVIDENCE_LINE = "evidence: run=synthetic-17 symbol=2330.TW exit_code=2\n"


def mutated_redactor(kind):
    """只改記憶體 AST；負向與過度去敏都使用同一份守門斷言。"""
    tree = ast.parse(inspect.getsource(instance.redact_command_log))
    changes = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if kind == "unredacted" and node.func.attr == "replace":
            node.func.attr = "removeprefix"
            node.args = [ast.Constant("__synthetic_prefix_never_present__")]
            changes.append(node)
        elif kind == "cleared_log" and node.func.attr == "write_text":
            node.args[0] = ast.Constant("")
            changes.append(node)
    if not changes:
        raise AssertionError(f"mutation 沒有命中 source：{kind}")
    namespace = dict(instance.__dict__)
    exec(compile(ast.fix_missing_locations(tree), "<helper-mutation>", "exec"), namespace)
    return namespace["redact_command_log"]


class HelperChecks(unittest.TestCase):
    mutation_checks = []

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dsa-helper-check-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "synthetic-repo"
        self.root.mkdir()
        self.run = self.root / "owned-run"
        (self.run / "runtime").mkdir(parents=True)
        self.env_path = self.run / "runtime/verification.env"
        self.settings = {
            "ENV_FILE": str(self.env_path),
            "DATABASE_PATH": str(self.run / "runtime/state/application.db"),
            "STORAGE_DATABASE_URL": "", "DATABASE_URL": "",
            "GENERATION_BACKEND": "claude_code_cli", "GENERATION_FALLBACK_BACKEND": "",
            "REPORT_LANGUAGE": "zh-TW", "SCHEDULE_ENABLED": "false",
        }
        self.env_path.write_text(
            "".join(f"{key}={value}\n" for key, value in self.settings.items()), encoding="utf-8",
        )
        self.repo_values = {"DATABASE_URL": SYNTHETIC_URL}
        self.parent = {
            "PATH": "/synthetic/bin", "LANG": "C.UTF-8", "HOME": str(self.root / "cli-home"),
            "USER": "synthetic-user", "LOGNAME": "synthetic-login",
            "ENV_FILE": "/synthetic/parent.env", "DATABASE_URL": "synthetic-parent-db",
            "STORAGE_DATABASE_URL": "synthetic-parent-storage", "PGOPTIONS": "synthetic-parent-options",
        }
        self.secret_keys = (
            "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_MESSAGE_THREAD_ID",
            "TELEGRAM_TOPIC_REPORT", "SHIOAJI_API_KEY", "SHIOAJI_SECRET_KEY",
            "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "FINMIND_TOKEN",
        )
        self.parent.update({key: f"synthetic-secret-{key}" for key in self.secret_keys})
        # 攔在實際 dotenv 邊界；未知路徑直接失敗，永不退回讀真 .env。
        for mocker in (
            patch.dict(os.environ, self.parent, clear=True),
            patch.object(instance, "ROOT", self.root),
            patch("dotenv.dotenv_values", side_effect=self.read_synthetic_env),
        ):
            mocker.start()
            self.addCleanup(mocker.stop)

    def read_synthetic_env(self, path):
        if Path(path) == self.env_path:
            return dict(self.settings)
        if Path(path) == self.root / ".env":
            return dict(self.repo_values)
        raise AssertionError("dotenv 請求不屬於本測試的合成路徑")

    def assert_no_parent_secrets(self, child):
        for key in self.secret_keys:
            self.assertNotIn(key, child)
            self.assertNotIn(self.parent[key], child.values())

    def test_online_preserves_cli_identity_and_selected_connection(self):
        child = instance.environment(self.run, online=True)
        for key in ("HOME", "USER", "LOGNAME", "PATH", "LANG"):
            self.assertEqual(child[key], self.parent[key])
        self.assertEqual(child["DATABASE_URL"], SYNTHETIC_URL)
        self.assertEqual(child["PGOPTIONS"], "-c default_transaction_read_only=on")
        self.assertEqual(child["ENV_FILE"], str(self.env_path))
        self.assertEqual(child["DATABASE_PATH"], self.settings["DATABASE_PATH"])
        self.assertEqual(child["STORAGE_DATABASE_URL"], "")
        self.assertEqual(child["GENERATION_BACKEND"], "claude_code_cli")
        self.assertEqual(child["GENERATION_FALLBACK_BACKEND"], "")
        self.assertEqual(child["REPORT_LANGUAGE"], "zh-TW")
        self.assert_no_parent_secrets(child)

    def test_online_rejects_missing_connection(self):
        self.repo_values.clear()
        with self.assertRaisesRegex(RuntimeError, "DATABASE_URL"):
            instance.environment(self.run, online=True)

    def test_offline_uses_empty_home_and_local_database(self):
        # 離線路徑若開始讀 repo 設定，這個邊界會立即使測試失敗。
        with patch("dotenv.dotenv_values", side_effect=lambda path: (
            dict(self.settings) if Path(path) == self.env_path else self.fail("離線讀了 repo .env")
        )):
            child = instance.environment(self.run, online=False)
        self.assertEqual(child["HOME"], str(self.run / "runtime/home"))
        self.assertEqual(list(Path(child["HOME"]).iterdir()), [])
        self.assertEqual(child["DATABASE_URL"], "")
        self.assertEqual(child["STORAGE_DATABASE_URL"], "")
        self.assertEqual(child["DATABASE_PATH"], self.settings["DATABASE_PATH"])
        for key in ("USER", "LOGNAME", "PGOPTIONS"):
            self.assertNotIn(key, child)
        self.assert_no_parent_secrets(child)

    def error_log(self):
        path = self.run / "owned-command.log"
        path.write_text(
            f'{ERROR_PREFIX}"{SYNTHETIC_URL}" in connection info string\n'
            f"authentication detail: password={SYNTHETIC_PASSWORD}\n{EVIDENCE_LINE}"
            "Traceback: synthetic_frame.py:17\n", encoding="utf-8",
        )
        return path

    def assert_redacted_error_and_evidence(self, path):
        content = path.read_text(encoding="utf-8")
        for sensitive in (SYNTHETIC_URL, SYNTHETIC_PASSWORD, "helper_user", "market.invalid"):
            self.assertNotIn(sensitive, content)
        for preserved in (ERROR_PREFIX, "in connection info string", "authentication detail:",
                          EVIDENCE_LINE, "Traceback: synthetic_frame.py:17\n"):
            self.assertIn(preserved, content)

    def test_redacts_raw_sqlalchemy_url_and_decoded_password(self):
        path = self.error_log()
        instance.redact_command_log(path)
        self.assert_redacted_error_and_evidence(path)

    def test_without_configured_url_preserves_nonsecret_error(self):
        self.repo_values.clear()
        path = self.run / "owned-nonsecret.log"
        content = f"ValueError: synthetic invalid command\n{EVIDENCE_LINE}"
        path.write_text(content, encoding="utf-8")
        instance.redact_command_log(path)
        self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_mutations_reject_unredacted_and_cleared_log(self):
        for kind in ("unredacted", "cleared_log"):
            with self.subTest(mutation=kind):
                path = self.error_log()
                mutated_redactor(kind)(path)
                with self.assertRaises(AssertionError):
                    self.assert_redacted_error_and_evidence(path)
                self.mutation_checks.append({"mutation": kind, "detected": True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HelperChecks)
    collected = suite.countTestCases()
    with (output / "tests.log").open("w", encoding="utf-8") as log:
        with redirect_stdout(log), redirect_stderr(log):
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    summary = {
        "command": [sys.executable, *sys.argv], "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "collected": collected, "run": result.testsRun,
        "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
        "failed": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
        "mutation_checks": HelperChecks.mutation_checks, "exit_code": 0 if result.wasSuccessful() else 1,
        "scope": "synthetic dotenv boundary and owned temporary files; no external services",
    }
    (output / "results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
