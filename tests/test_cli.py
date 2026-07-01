import argparse
import contextlib
import io
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from kgnite.cli import KgniteError, command_preview, validate_resource_handle


class HandleValidationTests(unittest.TestCase):
    def test_dataset_query_is_not_accepted_as_a_handle(self):
        with self.assertRaisesRegex(KgniteError, "owner/dataset-slug"):
            validate_resource_handle("dataset", "employee")

    def test_dataset_ref_is_accepted(self):
        validate_resource_handle("dataset", "tawfikelmetwally/employee-dataset")

    def test_competition_slug_is_accepted(self):
        validate_resource_handle("competition", "titanic")

    def test_notebook_requires_owner(self):
        with self.assertRaisesRegex(KgniteError, "owner/notebook-slug"):
            validate_resource_handle("notebook", "starter")


class PreviewCommandTests(unittest.TestCase):
    def preview_args(
        self, resource: str, source: str, columns: str = "all"
    ) -> argparse.Namespace:
        return argparse.Namespace(
            resource=resource,
            source=source,
            path=None,
            rows=10,
            columns=columns,
            max_file_size_mb=1.0,
            force=False,
            json=True,
        )

    def test_absolute_local_preview_reports_shape_and_all_columns(self):
        fixture = (Path(__file__).parent / "fixtures" / "employees.csv").resolve()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            command_preview(self.preview_args("local", str(fixture)))
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["shape"], {"rows": 3, "columns": 5})
        self.assertEqual(payload["displayed_columns"], 5)
        self.assertEqual(len(payload["rows"]), 3)

    def test_local_preview_requires_absolute_path(self):
        with self.assertRaisesRegex(KgniteError, "absolute workstation path"):
            command_preview(self.preview_args("local", "relative.csv"))

    def test_url_preview_streams_csv_and_reports_shape(self):
        data = (Path(__file__).parent / "fixtures" / "employees.csv").read_bytes()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/csv")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            output = io.StringIO()
            url = f"http://127.0.0.1:{server.server_port}/employees.csv"
            with contextlib.redirect_stdout(output):
                command_preview(self.preview_args("url", url, "10"))
            payload = json.loads(output.getvalue())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(payload["shape"], {"rows": 3, "columns": 5})
        self.assertEqual(payload["displayed_columns"], 5)


if __name__ == "__main__":
    unittest.main()
