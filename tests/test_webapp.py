import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from kgnite.webapp import (
    WebSession,
    guide_html,
    make_handler,
    page_html,
    parse_command,
    run_command,
)


class CommandTests(unittest.TestCase):
    def test_parse_command_accepts_optional_program_name(self):
        self.assertEqual(
            parse_command('kgnite search datasets "house prices" --json'),
            ["search", "datasets", "house prices", "--json"],
        )

    def test_parse_command_rejects_web_and_unknown_commands(self):
        with self.assertRaises(ValueError):
            parse_command("kgnite web")
        with self.assertRaises(ValueError):
            parse_command("rm -rf /tmp/example")

    def test_run_command_does_not_use_a_shell(self):
        with tempfile.TemporaryDirectory() as temp:
            session = WebSession("token", Path(temp), 30, 10)
            response = run_command(["usage"], session)
        self.assertTrue(response["ok"])
        self.assertIn("Common workflows", response["stdout"])


class PageTests(unittest.TestCase):
    def test_page_contains_token_and_core_workflows(self):
        page = page_html("secret-token", Path("/workspace"))
        self.assertIn("secret-token", page)
        self.assertIn("Set up competition", page)
        self.assertIn("Performance history", page)
        self.assertIn("Advanced command runner", page)
        self.assertIn('id="tableView"', page)
        self.assertIn('id="jsonView"', page)
        self.assertIn("td.textContent=scalar", page)
        self.assertIn("width:max-content", page)
        self.assertIn("overflow-x:auto", page)
        self.assertIn("Scroll horizontally", page)
        self.assertIn("Scrollable tabular results", page)
        self.assertIn("f.getAttribute('data-action')", page)
        self.assertNotIn("f.dataset.action", page)
        self.assertIn(".filter(Boolean).join('\\n')", page)
        self.assertNotIn(".filter(Boolean).join('\n')", page)

    def test_page_exposes_all_non_recursive_cli_workflows(self):
        page = page_html("token", Path("/workspace"))
        actions = {
            "search",
            "trending",
            "setup",
            "template",
            "performance",
            "preview",
            "submit",
            "inspect",
            "download",
            "submissions",
            "leaderboard",
            "pull",
            "uploadDataset",
            "uploadModel",
            "doctor",
            "usage",
            "completions",
        }
        for action in actions:
            self.assertIn(f'data-action="{action}"', page)

    def test_page_links_to_comprehensive_web_guide(self):
        page = page_html("secret-token", Path("/workspace"))
        guide = guide_html("secret-token")
        self.assertIn('href="/guide"', page)
        self.assertIn("Queries and handles", guide)
        self.assertIn("tawfikelmetwally/employee-dataset", guide)
        self.assertIn("Upload datasets and models", guide)
        self.assertIn("secret-token", guide)

    def test_completion_install_is_blocked_but_print_is_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            session = WebSession("token", Path(temp), 30, 10)
            with self.assertRaisesRegex(ValueError, "requires --print"):
                run_command(["completions", "--shell", "zsh"], session)
            response = run_command(
                ["completions", "--shell", "zsh", "--print"], session
            )
        self.assertTrue(response["ok"])
        self.assertIn("#compdef kgnite", response["stdout"])

    def test_session_expires_after_connected_heartbeat_stops(self):
        session = WebSession("token", Path.cwd(), 0.01, 10)
        self.assertFalse(session.expired())
        session.heartbeat()
        time.sleep(0.02)
        self.assertTrue(session.expired())


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.session = WebSession("test-token", Path.cwd(), 30, 10)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.session))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_home_heartbeat_and_command_api(self):
        with urllib.request.urlopen(self.base + "/") as response:
            self.assertIn(b"kgnite workstation", response.read())

        heartbeat = urllib.request.Request(
            self.base + "/api/heartbeat",
            method="POST",
            headers={"X-Kgnite-Token": "test-token"},
        )
        with urllib.request.urlopen(heartbeat) as response:
            self.assertEqual(json.loads(response.read()), {"ok": True})

        body = json.dumps({"arguments": ["usage"]}).encode()
        command = urllib.request.Request(
            self.base + "/api/run",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Kgnite-Token": "test-token",
            },
        )
        with urllib.request.urlopen(command) as response:
            payload = json.loads(response.read())
        self.assertTrue(payload["ok"])

    def test_api_rejects_missing_token(self):
        request = urllib.request.Request(self.base + "/api/heartbeat", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request)
        self.assertEqual(context.exception.code, 403)
        context.exception.close()

    def test_guide_route_is_available(self):
        with urllib.request.urlopen(self.base + "/guide") as response:
            page = response.read().decode()
        self.assertIn("kgnite Web Guide", page)
        self.assertIn("Back to workstation", page)


if __name__ == "__main__":
    unittest.main()
