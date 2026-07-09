import json
import tempfile
import unittest
from pathlib import Path

from kgnite.features import (
    choose_preview_file,
    create_competition_workspace,
    create_project_workspace,
    filter_resource_rows,
    merge_score_history,
    next_competition_notebook_path,
    normalize_scores,
    preview_local_file,
    prepare_kaggle_notebook_bundle,
    prepare_local_dataset_bundle,
    sanitize_competition_notes,
    score_sparkline,
    write_starter_notebook,
)


class FilteringTests(unittest.TestCase):
    def test_tags_and_keywords_match_across_columns(self):
        rows = [
            {"title": "House Prices", "tags": "tabular regression", "owner": "alice"},
            {"title": "Cat Images", "tags": "vision", "owner": "bob"},
        ]
        self.assertEqual(
            filter_resource_rows(rows, tags=["tabular"], keywords=["house"]),
            [rows[0]],
        )

    def test_all_filters_are_required(self):
        rows = [{"title": "NLP", "tags": "text"}]
        self.assertEqual(filter_resource_rows(rows, tags=["text", "audio"]), [])


class PreviewTests(unittest.TestCase):
    def test_preview_selects_small_non_sample_tabular_file(self):
        files = [
            {"name": "sample_submission.csv", "size": "20"},
            {"name": "employees.csv", "size": "100"},
            {"name": "archive.zip", "size": "10"},
        ]
        self.assertEqual(
            choose_preview_file(files, max_bytes=1000),
            ("employees.csv", 100),
        )

    def test_preview_rejects_large_or_unsupported_file(self):
        with self.assertRaisesRegex(ValueError, "above the preview limit"):
            choose_preview_file([{"name": "large.csv", "size": "2000"}], max_bytes=100)
        with self.assertRaisesRegex(ValueError, "cannot be previewed"):
            choose_preview_file(
                [{"name": "data.parquet", "size": "20"}], "data.parquet", max_bytes=100
            )

    def test_csv_preview_limits_rows_and_columns(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "employees.csv"
            path.write_text("name,team,age\nAda,ML,36\nLin,Data,40\n")
            preview = preview_local_file(path, row_limit=1, column_limit=2)
        self.assertEqual(preview["rows"], [{"name": "Ada", "team": "ML"}])
        self.assertEqual(preview["shape"], {"rows": 2, "columns": 3})
        self.assertEqual(preview["columns"], ["name", "team", "age"])

    def test_csv_preview_can_show_all_columns(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "employees.csv"
            path.write_text("name,team,age\nAda,ML,36\n")
            preview = preview_local_file(path, row_limit=10, column_limit=None)
        self.assertEqual(preview["displayed_columns"], 3)
        self.assertEqual(preview["rows"][0], {"name": "Ada", "team": "ML", "age": "36"})


class WorkspaceTests(unittest.TestCase):
    def test_kaggle_notebook_bundle_contains_notebook_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            notebook = root / "notebooks" / "titanic-01.ipynb"
            notebook.parent.mkdir()
            notebook.write_text('{"nbformat": 4}')
            bundle = root / "kaggle-notebooks" / "titanic-rf"
            payload = prepare_kaggle_notebook_bundle(
                notebook,
                bundle,
                handle="rajinh/titanic-rf",
                title="Titanic Random Forest",
                competition="titanic",
                dataset_sources=["rajinh/extra-data"],
                kernel_sources=["rajinh/source-notebook"],
                model_sources=["rajinh/model/sklearn/v1"],
                public=True,
            )
            metadata = json.loads((bundle / "kernel-metadata.json").read_text())
            self.assertEqual(metadata["code_file"], "titanic-01.ipynb")
            self.assertEqual(metadata["competition_sources"], ["titanic"])
            self.assertEqual(metadata["dataset_sources"], ["rajinh/extra-data"])
            self.assertEqual(metadata["kernel_sources"], ["rajinh/source-notebook"])
            self.assertEqual(metadata["model_sources"], ["rajinh/model/sklearn/v1"])
            self.assertEqual(metadata["is_private"], "false")
            self.assertTrue((bundle / "titanic-01.ipynb").is_file())
            self.assertIn("push-notebook", payload["push_command"])

    def test_prepare_repairs_missing_generated_find_csv_helper(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            notebook = root / "titanic-01.ipynb"
            notebook.write_text(
                json.dumps(
                    {
                        "nbformat": 4,
                        "cells": [
                            {
                                "cell_type": "code",
                                "id": "data-loading",
                                "metadata": {},
                                "execution_count": None,
                                "outputs": [],
                                "source": ["train = find_csv('train')\n"],
                            }
                        ],
                    }
                )
            )
            payload = prepare_kaggle_notebook_bundle(
                notebook,
                root / "bundle",
                handle="rajinh/titanic-rf",
                title="Titanic RF",
                competition="titanic",
            )
            prepared = json.loads(Path(payload["notebook"]).read_text())
            self.assertIn("def find_csv(fragment):", "".join(prepared["cells"][0]["source"]))
            self.assertIn("Restored missing find_csv helper", payload["repairs"][0])

    def test_prepare_upgrades_local_fallback_for_kaggle_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            notebook = root / "titanic-01.ipynb"
            notebook.write_text(
                json.dumps(
                    {
                        "nbformat": 4,
                        "cells": [
                            {
                                "cell_type": "code",
                                "id": "data-setup",
                                "metadata": {},
                                "execution_count": None,
                                "outputs": [],
                                "source": [
                                    "from pathlib import Path\n",
                                    "KAGGLE_DATA_DIRS = ['/kaggle/input/titanic']\n",
                                    "KAGGLE_DATA_DIR = None\n",
                                    "WORKSPACE_CONFIG = None\n",
                                    "if KAGGLE_DATA_DIR:\n",
                                    "    DATA_DIR = KAGGLE_DATA_DIR\n",
                                    "else:\n",
                                    "    DATA_DIR = Path('/Users/test/titanic/data').expanduser().resolve()\n",
                                ],
                            }
                        ],
                    }
                )
            )
            payload = prepare_kaggle_notebook_bundle(
                notebook,
                root / "bundle",
                handle="rajinh/titanic-rf",
                title="Titanic RF",
                competition="titanic",
            )
            prepared = json.loads(Path(payload["notebook"]).read_text())
            source = "".join(prepared["cells"][0]["source"])
            self.assertIn("if KAGGLE_INPUT_ROOT.is_dir():", source)
            self.assertIn("DATA_DIR = KAGGLE_DATA_DIR or KAGGLE_INPUT_ROOT", source)
            self.assertIn("Upgraded data setup", payload["repairs"][0])

    def test_project_and_local_dataset_bundles_preserve_kaggle_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = create_project_workspace(
                "churn",
                root / "projects" / "churn",
                dataset_sources=["rajinh/churn-data"],
                kernel_sources=["rajinh/feature-notebook"],
                model_sources=["rajinh/churn/sklearn/v1"],
            )
            self.assertEqual(project["dataset_sources"], ["rajinh/churn-data"])
            project_help = Path(project["help"]).read_text()
            self.assertIn("Generic project actions", project_help)
            self.assertIn("--local-dataset ./data", project_help)
            source = root / "local-data"
            source.mkdir()
            (source / "train.csv").write_text("target\n1\n")
            bundle = root / "projects" / "churn" / "kaggle-datasets" / "churn-data"
            payload = prepare_local_dataset_bundle(
                source,
                bundle,
                handle="rajinh/churn-data",
                title="Churn Data",
            )
            metadata = json.loads((bundle / "dataset-metadata.json").read_text())
            self.assertEqual(metadata["id"], "rajinh/churn-data")
            self.assertTrue((bundle / "train.csv").is_file())
            self.assertIn("upload-dataset", payload["upload_command"])

    def test_next_notebook_path_uses_incrementing_numeric_suffix(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.assertEqual(
                next_competition_notebook_path(directory, "titanic"),
                directory / "titanic-01.ipynb",
            )
            (directory / "titanic-01.ipynb").touch()
            (directory / "titanic-02.ipynb").touch()
            self.assertEqual(
                next_competition_notebook_path(directory, "titanic"),
                directory / "titanic-03.ipynb",
            )

    def test_workspace_and_notebook_are_created(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "titanic"
            payload = create_competition_workspace("titanic", root)
            self.assertEqual(payload["competition"], "titanic")
            self.assertTrue((root / ".titanic-config.json").exists())
            self.assertTrue((root / "README.md").exists())
            help_text = (root / "README.md").read_text()
            self.assertIn("Folder and file guide", help_text)
            self.assertIn("kgnite submit titanic", help_text)
            self.assertIn("kgnite web", help_text)
            self.assertTrue((root / "submissions").is_dir())

            (root / "data" / "sample_submission.csv").write_text(
                "PassengerId,Survived\n1,0\n"
            )
            notebook_path = write_starter_notebook(
                "titanic",
                root / "notebooks" / "starter.ipynb",
                root / "data",
                participant="Rajesh Singh",
                competition_notes=[
                    {
                        "name": "data-description",
                        "url": "https://www.kaggle.com/competitions/titanic/data",
                        "content": "<h3>Data Dictionary</h3><p>Age in years</p>",
                    }
                ],
            )
            notebook = json.loads(notebook_path.read_text())
            self.assertEqual(notebook["nbformat"], 4)
            notebook_text = "\n".join(
                "".join(cell["source"]) for cell in notebook["cells"]
            )
            self.assertIn("Participant:** Rajesh Singh", notebook_text)
            self.assertNotIn("Generated by", notebook_text)
            self.assertIn("Data Dictionary", notebook_text)
            self.assertIn("PassengerId, Survived", notebook_text)
            self.assertIn("WORKSPACE_CONFIG", notebook_text)
            self.assertIn(".titanic-config.json", notebook_text)
            self.assertNotIn(".kgnite.json", notebook_text)
            self.assertIn("KAGGLE_INPUT_ROOT = Path('/kaggle/input')", notebook_text)
            self.assertIn("DATA_DIR = KAGGLE_DATA_DIR or KAGGLE_INPUT_ROOT", notebook_text)
            self.assertIn("find_csv('submission')", notebook_text)

    def test_nonstandard_submission_filename_is_discovered(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "data"
            data.mkdir()
            (data / "gender_submission.csv").write_text(
                "PassengerId,Survived\n1,0\n"
            )
            notebook_path = write_starter_notebook(
                "titanic",
                root / "notebooks" / "starter.ipynb",
                data,
                participant="Tester",
            )
            self.assertIn("PassengerId, Survived", notebook_path.read_text())

    def test_competition_notes_sanitizer_removes_active_content(self):
        content = '<h3>Notes</h3><script>alert(1)</script><a href="https://kaggle.com">Kaggle</a>'
        sanitized = sanitize_competition_notes(content)
        self.assertIn("<h3>Notes</h3>", sanitized)
        self.assertNotIn("script", sanitized)
        self.assertNotIn("alert", sanitized)
        self.assertIn('href="https://kaggle.com"', sanitized)

    def test_workspace_does_not_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create_competition_workspace("demo", root)
            with self.assertRaises(FileExistsError):
                create_competition_workspace("demo", root)


class PerformanceTests(unittest.TestCase):
    def test_scores_are_normalized_merged_and_visualized(self):
        raw = [
            {"date": "2026-01-01", "publicScore": "0.71", "description": "baseline"},
            {"date": "2026-01-02", "publicScore": "0.82", "description": "features"},
        ]
        scores = normalize_scores(raw, "demo")
        self.assertEqual([row["score"] for row in scores], [0.71, 0.82])
        self.assertEqual(len(merge_score_history(scores, scores)), 2)
        self.assertEqual(score_sparkline([0.71, 0.82]), "▁█")


if __name__ == "__main__":
    unittest.main()
