import argparse
import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from kgnite.cli import (
    KgniteError,
    command_prepare_notebook,
    command_preview,
    validate_resource_handle,
)


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


class PrepareNotebookCommandTests(unittest.TestCase):
    def prepare_args(self, notebook: Path, **overrides: object) -> argparse.Namespace:
        values = {
            "notebook": str(notebook),
            "handle": None,
            "competition": None,
            "dataset_source": None,
            "competition_source": None,
            "kernel_source": None,
            "model_source": None,
            "local_dataset": None,
            "dataset_handle": None,
            "dataset_title": None,
            "dataset_license": None,
            "title": None,
            "output_dir": None,
            "public": False,
            "enable_internet": False,
            "enable_gpu": False,
            "force": False,
            "json": True,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_title_only_derives_matching_handle_and_bundle_dir(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = root / "settings.json"
            previous = os.environ.get("KGNITE_SETTINGS_PATH")
            os.environ["KGNITE_SETTINGS_PATH"] = str(settings)
            try:
                notebook = root / "notebooks" / "iris.ipynb"
                notebook.parent.mkdir()
                notebook.write_text('{"nbformat": 4}')
                output = io.StringIO()
                args = self.prepare_args(
                    notebook,
                    title="Iris Flower Species Classification",
                    public=True,
                )
                with contextlib.redirect_stdout(output):
                    command_prepare_notebook(args)
                payload = json.loads(output.getvalue())
            finally:
                if previous is None:
                    os.environ.pop("KGNITE_SETTINGS_PATH", None)
                else:
                    os.environ["KGNITE_SETTINGS_PATH"] = previous
        self.assertEqual(payload["handle"], "rajinh/iris-flower-species-classification")
        self.assertTrue(payload["bundle_dir"].endswith("kaggle-notebooks/iris-flower-species-classification"))

    def test_title_wins_when_handle_slug_does_not_match(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            notebook = root / "notebooks" / "iris.ipynb"
            notebook.parent.mkdir()
            notebook.write_text('{"nbformat": 4}')
            output = io.StringIO()
            args = self.prepare_args(
                notebook,
                handle="rajinh/iris-classification",
                title="Iris Flower Species Classification",
            )
            with contextlib.redirect_stdout(output):
                command_prepare_notebook(args)
            payload = json.loads(output.getvalue())
        self.assertEqual(payload["handle"], "rajinh/iris-flower-species-classification")
        self.assertIn("Adjusted notebook handle", payload["notices"][0])


if __name__ == "__main__":
    unittest.main()
