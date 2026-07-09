from __future__ import annotations

import ast
import csv
import html
import json
import math
import re
import shutil
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from html.parser import HTMLParser
from typing import Any, Iterable


SCORE_KEYS = ("publicScore", "privateScore", "score")
DATE_KEYS = ("date", "submittedAt", "submissionDate", "createdAt")
PREVIEWABLE_SUFFIXES = {".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".txt"}
SAFE_NOTE_TAGS = {
    "a",
    "b",
    "blockquote",
    "br",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "i",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}


def kaggle_notebook_slug(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title)
    ascii_title = normalized.encode("ascii", "ignore").decode("ascii").casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title).strip("-")
    slug = re.sub(r"-+", "-", slug)
    if not slug:
        raise ValueError("Notebook title must contain at least one letter or number.")
    if len(slug) < 5:
        raise ValueError(
            "Kaggle notebook slug derived from title must be at least five characters."
        )
    return slug


def notebook_title_from_slug(slug: str) -> str:
    words = [word for word in re.split(r"[-_]+", slug.strip()) if word]
    return " ".join(word.capitalize() for word in words) or slug


def workspace_help(name: str, *, project_type: str) -> str:
    config_name = f".{name}-config.json"
    common = f"""# {name} workspace

This workspace is managed with kgnite. Run commands from this directory unless a command uses an absolute path.

## Folder and file guide

| Path | Purpose |
|---|---|
| `{config_name}` | Workspace settings and Kaggle source references. This is a hidden file. |
| `data/` | Local training, test, reference, or generated data. Do not assume these files exist on Kaggle. |
| `notebooks/` | Editable local notebooks. Numbered names such as `{name}-01.ipynb` preserve experiments. |
| `submissions/` | Competition submission CSV or ZIP files. |
| `kaggle-notebooks/` | Prepared notebook bundles containing `kernel-metadata.json`. |
| `kaggle-datasets/` | Prepared local dataset bundles containing `dataset-metadata.json`. |
| `README.md` | This reference guide. |

## Local and Kaggle data paths

kgnite-generated notebooks use local `data/` while running on this workstation. Prepared copies resolve configured Kaggle sources under `/kaggle/input/<source-slug>` when running on Kaggle.

The four source lists written to `kernel-metadata.json` are:

- `dataset_sources`: Kaggle datasets, including staged local datasets after upload.
- `competition_sources`: competition datasets such as `{name}`.
- `kernel_sources`: other Kaggle notebooks used as inputs.
- `model_sources`: Kaggle model handles used by the notebook.

## Notebook workflow

Create another numbered notebook:

```bash
kgnite template {name} --data-dir ./data --no-competition-notes
```

Prepare a notebook for your Kaggle profile:

```bash
kgnite prepare-notebook ./notebooks/{name}-01.ipynb \\
  --title "{name.replace('-', ' ').title()} Notebook" \\
  --competition {name} \\
  --public
```

Review `kaggle-notebooks/<notebook-slug>/kernel-metadata.json`, then publish:

```bash
kgnite push-notebook ./kaggle-notebooks/<notebook-slug>
```

For a staged local dataset, publish it before the notebook automatically:

```bash
kgnite push-notebook ./kaggle-notebooks/<notebook-slug> --with-datasets
```

Use `--dataset-action version` when that dataset already exists on Kaggle.

## Web application

```bash
kgnite web
```

- **Competition**: download data, generate notebooks, submit results, and track scores.
- **Projects**: create generic Kaggle-ready workspaces.
- **Uploads**: prepare or push notebooks and datasets.
- **Settings**: change the root workspace, folder names, username, and dataset license.
- **Resources**: inspect or download Kaggle datasets, competitions, notebooks, and models.

The web header shows the directory used to resolve relative paths. Publishing and submission actions require confirmation.

## Troubleshooting

- Empty `data/`: run `kgnite download competition {name} --output-dir ./data`.
- Competition notes return 403: generate with `--no-competition-notes`.
- Kaggle cannot find data: check the source arrays in `kernel-metadata.json` and confirm the dataset was uploaded before the notebook.
- Existing local dataset: use `--dataset-action version` rather than `create`.
- Show hidden config files: run `ls -la` or `tree -a`.
"""
    if project_type == "competition":
        return common + f"""

## Competition actions

Download or refresh competition data:

```bash
kgnite download competition {name} --output-dir ./data --force
```

Submit a prepared result:

```bash
kgnite submit {name} --file ./submissions/submission.csv --message "experiment description"
```

Review submissions and performance:

```bash
kgnite submissions {name}
kgnite performance {name} --sync
```
"""
    return common + """

## Generic project actions

Add Kaggle sources while preparing a notebook with repeatable options:

```bash
kgnite prepare-notebook ./notebooks/<notebook>.ipynb \\
  --title "<Notebook Title>" \\
  --dataset-source <owner/dataset> \\
  --kernel-source <owner/notebook> \\
  --model-source <owner/model/framework/variation>
```

Stage local project data as a Kaggle dataset:

```bash
kgnite prepare-notebook ./notebooks/<notebook>.ipynb \\
  --title "<Notebook Title>" \\
  --local-dataset ./data \\
  --dataset-handle <kaggle-username>/<dataset-slug>
```
"""


def write_workspace_help(directory: Path, name: str, *, project_type: str) -> Path:
    path = directory / "README.md"
    path.write_text(workspace_help(name, project_type=project_type))
    return path


class CompetitionNotesSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.blocked_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "iframe", "object"}:
            self.blocked_depth += 1
            return
        if self.blocked_depth or tag not in SAFE_NOTE_TAGS:
            return
        rendered_attrs = ""
        if tag == "a":
            href = next(
                (value for key, value in attrs if key.casefold() == "href"), None
            )
            if href and href.startswith(("https://", "http://")):
                rendered_attrs = (
                    f' href="{html.escape(href, quote=True)}" target="_blank"'
                )
        self.parts.append(f"<{tag}{rendered_attrs}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "iframe", "object"}:
            self.blocked_depth = max(0, self.blocked_depth - 1)
            return
        if not self.blocked_depth and tag in SAFE_NOTE_TAGS and tag != "br":
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.blocked_depth:
            self.parts.append(html.escape(data))


def sanitize_competition_notes(content: str) -> str:
    sanitizer = CompetitionNotesSanitizer()
    sanitizer.feed(content)
    sanitizer.close()
    return "".join(sanitizer.parts).strip()


def filter_resource_rows(
    rows: list[dict[str, str]],
    *,
    tags: Iterable[str] = (),
    keywords: Iterable[str] = (),
) -> list[dict[str, str]]:
    """Filter Kaggle CSV rows without relying on resource-specific column names."""
    wanted_tags = [value.casefold() for value in tags if value]
    wanted_keywords = [value.casefold() for value in keywords if value]
    filtered: list[dict[str, str]] = []
    for row in rows:
        searchable = " ".join(str(value) for value in row.values()).casefold()
        if wanted_tags and not all(tag in searchable for tag in wanted_tags):
            continue
        if wanted_keywords and not all(
            keyword in searchable for keyword in wanted_keywords
        ):
            continue
        filtered.append(row)
    return filtered


def choose_preview_file(
    files: list[dict[str, Any]],
    requested_path: str | None = None,
    *,
    max_bytes: int,
) -> tuple[str, int | None]:
    normalized: list[tuple[str, int | None]] = []
    for item in files:
        name = str(item.get("name") or item.get("ref") or item.get("fileName") or "")
        try:
            size = int(item.get("size")) if item.get("size") not in (None, "") else None
        except (TypeError, ValueError):
            size = None
        if name:
            normalized.append((name, size))
    if requested_path:
        match = next((item for item in normalized if item[0] == requested_path), None)
        if match is None:
            raise ValueError(f"Dataset file was not found: {requested_path}")
        candidates = [match]
    else:
        candidates = [
            item
            for item in normalized
            if Path(item[0]).suffix.lower() in PREVIEWABLE_SUFFIXES
        ]
        candidates.sort(
            key=lambda item: (
                "sample" in item[0].casefold(),
                item[1] is None,
                item[1] or 0,
                item[0].casefold(),
            )
        )
    if not candidates:
        supported = ", ".join(sorted(PREVIEWABLE_SUFFIXES))
        raise ValueError(
            f"No previewable file found. Supported file types: {supported}"
        )
    name, size = candidates[0]
    suffix = Path(name).suffix.lower()
    if suffix not in PREVIEWABLE_SUFFIXES:
        supported = ", ".join(sorted(PREVIEWABLE_SUFFIXES))
        raise ValueError(
            f"File type `{suffix or 'unknown'}` cannot be previewed. Supported: {supported}"
        )
    if size is not None and size > max_bytes:
        raise ValueError(
            f"Selected file is {size / 1024 / 1024:.1f} MB, above the preview limit of "
            f"{max_bytes / 1024 / 1024:.1f} MB. Choose a smaller --path or raise --max-file-size-mb."
        )
    return name, size


def preview_local_file(
    path: Path, *, row_limit: int, column_limit: int | None
) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
            reader = csv.DictReader(handle, delimiter="\t" if suffix == ".tsv" else ",")
            all_fields = reader.fieldnames or []
            fields = all_fields if column_limit is None else all_fields[:column_limit]
            rows: list[dict[str, Any]] = []
            total_rows = 0
            for row in reader:
                if total_rows < row_limit:
                    rows.append({field: row.get(field, "") for field in fields})
                total_rows += 1
            return _preview_result(rows, total_rows, all_fields)
    if suffix in {".jsonl", ".ndjson"}:
        rows: list[dict[str, Any]] = []
        total_rows = 0
        all_columns: list[str] = []
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                value = json.loads(line)
                full_row = _preview_row(value, None)
                for column in full_row:
                    if column not in all_columns:
                        all_columns.append(column)
                if total_rows < row_limit:
                    rows.append(_preview_row(value, column_limit))
                total_rows += 1
        return _preview_result(rows, total_rows, all_columns)
    if suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        values = value if isinstance(value, list) else [value]
        all_columns: list[str] = []
        for item in values:
            for column in _preview_row(item, None):
                if column not in all_columns:
                    all_columns.append(column)
        rows = [_preview_row(item, column_limit) for item in values[:row_limit]]
        return _preview_result(rows, len(values), all_columns)
    if suffix == ".txt":
        with path.open(encoding="utf-8", errors="replace") as handle:
            rows = []
            total_rows = 0
            for line in handle:
                if total_rows < row_limit:
                    rows.append({"line": total_rows + 1, "text": line.rstrip("\n")})
                total_rows += 1
            return _preview_result(rows, total_rows, ["line", "text"])
    raise ValueError(f"Unsupported preview file type: {suffix}")


def _preview_row(value: Any, column_limit: int | None) -> dict[str, Any]:
    if isinstance(value, dict):
        items = list(value.items())
        return dict(items if column_limit is None else items[:column_limit])
    return {"value": value}


def _preview_result(
    rows: list[dict[str, Any]], total_rows: int, columns: list[str]
) -> dict[str, Any]:
    return {
        "rows": rows,
        "shape": {"rows": total_rows, "columns": len(columns)},
        "columns": columns,
        "displayed_rows": len(rows),
        "displayed_columns": len(rows[0]) if rows else min(len(columns), 0),
    }


def create_competition_workspace(
    competition: str,
    directory: Path,
    *,
    metric: str = "publicScore",
    lower_is_better: bool = False,
    participant: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    directory = directory.expanduser().resolve()
    config_path = directory / f".{competition}-config.json"
    if config_path.exists() and not force:
        raise FileExistsError(f"Workspace already exists: {config_path}")
    for child in ("data", "notebooks", "submissions", "kaggle-notebooks", "kaggle-datasets"):
        (directory / child).mkdir(parents=True, exist_ok=True)
    config = {
        "competition": competition,
        "metric": metric,
        "lower_is_better": lower_is_better,
        "participant": participant,
        "data_dir": "data",
        "notebook_dir": "notebooks",
        "submission_dir": "submissions",
        "dataset_sources": [],
        "competition_sources": [competition],
        "kernel_sources": [],
        "model_sources": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    help_path = write_workspace_help(directory, competition, project_type="competition")
    return {
        "directory": str(directory),
        "config": str(config_path),
        "help": str(help_path),
        **config,
    }


def discover_sample_columns(data_dir: Path) -> list[str]:
    candidates = sorted(data_dir.glob("**/*submission*.csv"))
    if not candidates:
        return []
    with candidates[0].open(newline="", encoding="utf-8-sig") as handle:
        return next(csv.reader(handle), [])


def next_competition_notebook_path(directory: Path, competition: str) -> Path:
    """Return the first available numbered notebook path for a competition."""
    directory = directory.expanduser()
    sequence = 1
    while True:
        candidate = directory / f"{competition}-{sequence:02d}.ipynb"
        if not candidate.exists():
            return candidate
        sequence += 1


def portable_data_setup_source(
    config_name: str, data_dir: str, kaggle_slugs: list[str]
) -> list[str]:
    kaggle_paths = [f"/kaggle/input/{slug}" for slug in kaggle_slugs]
    return [
        "from pathlib import Path\n",
        "import json\n",
        "import pandas as pd\n",
        "\n",
        "KAGGLE_INPUT_ROOT = Path('/kaggle/input')\n",
        f"KAGGLE_DATA_DIRS = {kaggle_paths!r}\n",
        "KAGGLE_DATA_DIR = next((Path(path) for path in KAGGLE_DATA_DIRS if Path(path).is_dir()), None)\n",
        "WORKSPACE_CONFIG = next(\n",
        f"    (directory / {config_name!r} for directory in (Path.cwd(), *Path.cwd().parents)\n",
        f"     if (directory / {config_name!r}).is_file()),\n",
        "    None,\n",
        ")\n",
        "if KAGGLE_INPUT_ROOT.is_dir():\n",
        "    # Kaggle may mount a source under a path different from its slug.\n",
        "    # Search the full input root when the configured directory is unavailable.\n",
        "    DATA_DIR = KAGGLE_DATA_DIR or KAGGLE_INPUT_ROOT\n",
        "elif WORKSPACE_CONFIG:\n",
        "    workspace = WORKSPACE_CONFIG.parent\n",
        "    config = json.loads(WORKSPACE_CONFIG.read_text())\n",
        "    DATA_DIR = (workspace / config.get('data_dir', 'data')).resolve()\n",
        "else:\n",
        f"    DATA_DIR = Path({data_dir!r}).expanduser().resolve()\n",
        "files = sorted(DATA_DIR.glob('**/*'))\n",
        "[str(path) for path in files if path.is_file()][:20]\n",
    ]


def prepare_kaggle_notebook_bundle(
    notebook: Path,
    output_dir: Path,
    *,
    handle: str,
    title: str,
    competition: str | None = None,
    dataset_sources: list[str] | None = None,
    competition_sources: list[str] | None = None,
    kernel_sources: list[str] | None = None,
    model_sources: list[str] | None = None,
    public: bool = False,
    enable_internet: bool = False,
    enable_gpu: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    notebook = notebook.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not notebook.is_file() or notebook.suffix.casefold() != ".ipynb":
        raise ValueError(f"Notebook was not found: {notebook}")
    metadata_path = output_dir / "kernel-metadata.json"
    copied_notebook = output_dir / notebook.name
    if (metadata_path.exists() or copied_notebook.exists()) and not force:
        raise FileExistsError(f"Kaggle notebook bundle already exists: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    copied_notebook.write_bytes(notebook.read_bytes())
    resolved_competition_sources = list(
        competition_sources or ([competition] if competition else [])
    )
    source_slugs = [
        source.rsplit("/", 1)[-1]
        for source in [*(dataset_sources or []), *resolved_competition_sources]
    ]
    repairs: list[str] = []
    try:
        notebook_payload = json.loads(copied_notebook.read_text())
        replacement = f"KAGGLE_DATA_DIRS = {[f'/kaggle/input/{slug}' for slug in source_slugs]!r}\n"
        for cell in notebook_payload.get("cells", []):
            source = cell.get("source")
            if isinstance(source, list):
                cell["source"] = [
                    replacement if line.startswith("KAGGLE_DATA_DIRS = ") else line
                    for line in source
                ]
        setup_cell = next(
            (
                cell
                for cell in notebook_payload.get("cells", [])
                if cell.get("id") == "data-setup"
                and isinstance(cell.get("source"), list)
            ),
            None,
        )
        if setup_cell is not None:
            existing_setup = "".join(setup_cell["source"])
            local_data_dir = "./data"
            for line in setup_cell["source"]:
                if "DATA_DIR = Path(" in line and ").expanduser().resolve()" in line:
                    literal = line.split("DATA_DIR = Path(", 1)[1].split(").expanduser()", 1)[0]
                    try:
                        local_data_dir = str(ast.literal_eval(literal))
                    except (SyntaxError, ValueError):
                        pass
                    break
            config_name = f".{competition}-config.json" if competition else ".project-config.json"
            marker = "directory / "
            for line in setup_cell["source"]:
                if marker in line and "-config.json" in line:
                    literal = line.split(marker, 1)[1].split(" for directory", 1)[0]
                    try:
                        config_name = str(ast.literal_eval(literal))
                    except (SyntaxError, ValueError):
                        pass
                    break
            setup_cell["source"] = portable_data_setup_source(
                config_name, local_data_dir, source_slugs
            )
            if "KAGGLE_INPUT_ROOT" not in existing_setup:
                repairs.append(
                    "Upgraded data setup to discover Kaggle input mounts without falling back to a local path."
                )
        all_source = "\n".join(
            "".join(cell.get("source", []))
            for cell in notebook_payload.get("cells", [])
            if isinstance(cell.get("source"), list)
        )
        if "find_csv(" in all_source and "def find_csv(" not in all_source:
            loading_cell = next(
                (
                    cell
                    for cell in notebook_payload.get("cells", [])
                    if cell.get("id") == "data-loading"
                    and isinstance(cell.get("source"), list)
                ),
                None,
            )
            if loading_cell is not None:
                loading_cell["source"] = [
                    "def find_csv(fragment):\n",
                    "    matches = list(DATA_DIR.glob(f'**/*{fragment}*.csv'))\n",
                    "    return pd.read_csv(matches[0]) if matches else None\n",
                    "\n",
                    *loading_cell["source"],
                ]
                repairs.append("Restored missing find_csv helper in the data-loading cell.")
        copied_notebook.write_text(json.dumps(notebook_payload, indent=2) + "\n")
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    metadata = {
        "id": handle,
        "title": title,
        "code_file": notebook.name,
        "language": "python",
        "kernel_type": "notebook",
        "is_private": str(not public).lower(),
        "enable_gpu": str(enable_gpu).lower(),
        "enable_tpu": "false",
        "enable_internet": str(enable_internet).lower(),
        "machine_shape": "",
        "dataset_sources": list(dataset_sources or []),
        "competition_sources": resolved_competition_sources,
        "kernel_sources": list(kernel_sources or []),
        "model_sources": list(model_sources or []),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    return {
        "bundle_dir": str(output_dir),
        "notebook": str(copied_notebook),
        "metadata": str(metadata_path),
        "handle": handle,
        "competition": competition,
        "push_command": f"kgnite push-notebook {output_dir}",
        "repairs": repairs,
    }


def prepare_local_dataset_bundle(
    source_dir: Path,
    output_dir: Path,
    *,
    handle: str,
    title: str,
    license_name: str = "CC0-1.0",
    force: bool = False,
) -> dict[str, str]:
    source_dir = source_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not source_dir.is_dir():
        raise ValueError(f"Local dataset directory was not found: {source_dir}")
    metadata_path = output_dir / "dataset-metadata.json"
    if output_dir.exists() and any(output_dir.iterdir()) and not force:
        raise FileExistsError(f"Kaggle dataset bundle already exists: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    if force:
        for child in output_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    for child in source_dir.iterdir():
        destination = output_dir / child.name
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)
    metadata = {
        "id": handle,
        "title": title,
        "licenses": [{"name": license_name}],
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    return {
        "bundle_dir": str(output_dir),
        "metadata": str(metadata_path),
        "handle": handle,
        "upload_command": f"kgnite upload-dataset {output_dir} --public",
    }


def create_project_workspace(
    name: str,
    directory: Path,
    *,
    dataset_sources: list[str] | None = None,
    kernel_sources: list[str] | None = None,
    model_sources: list[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    directory = directory.expanduser().resolve()
    config_path = directory / f".{name}-config.json"
    if config_path.exists() and not force:
        raise FileExistsError(f"Project already exists: {config_path}")
    for child in ("data", "notebooks", "submissions", "kaggle-notebooks", "kaggle-datasets"):
        (directory / child).mkdir(parents=True, exist_ok=True)
    config = {
        "name": name,
        "project_type": "project",
        "data_dir": "data",
        "notebook_dir": "notebooks",
        "submission_dir": "submissions",
        "dataset_sources": list(dataset_sources or []),
        "competition_sources": [],
        "kernel_sources": list(kernel_sources or []),
        "model_sources": list(model_sources or []),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    help_path = write_workspace_help(directory, name, project_type="project")
    return {
        "directory": str(directory),
        "config": str(config_path),
        "help": str(help_path),
        **config,
    }


def starter_notebook(
    competition: str,
    data_dir: str,
    columns: list[str],
    *,
    participant: str,
    competition_notes: list[dict[str, str]] | None = None,
    kaggle_data_sources: list[str] | None = None,
) -> dict[str, Any]:
    config_name = f".{competition}-config.json"
    kaggle_slugs = [source.rsplit("/", 1)[-1] for source in (kaggle_data_sources or [competition])]
    column_note = (
        ", ".join(columns)
        if columns
        else "detected from sample_submission.csv at runtime"
    )
    cells = [
        {
            "cell_type": "markdown",
            "id": "project-introduction",
            "metadata": {},
            "source": [
                f"# {competition} starter notebook\n",
                f"**Participant:** {participant}\n\n",
                "Personal competition workspace for analysis, experimentation, and submission development.\n",
            ],
        },
        {
            "cell_type": "code",
            "id": "data-setup",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": portable_data_setup_source(config_name, data_dir, kaggle_slugs),
        },
        {
            "cell_type": "markdown",
            "id": "data-loading-notes",
            "metadata": {},
            "source": [
                "## Load competition data\n",
                f"Expected submission columns: `{column_note}`\n",
            ],
        },
        {
            "cell_type": "code",
            "id": "data-loading",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "def find_csv(fragment):\n",
                "    matches = list(DATA_DIR.glob(f'**/*{fragment}*.csv'))\n",
                "    return pd.read_csv(matches[0]) if matches else None\n",
                "\n",
                "train = find_csv('train')\n",
                "test = find_csv('test')\n",
                "sample_submission = find_csv('submission')\n",
                "[(name, None if frame is None else frame.shape) for name, frame in "
                "[('train', train), ('test', test), ('sample_submission', sample_submission)]]\n",
            ],
        },
        {
            "cell_type": "markdown",
            "id": "baseline-notes",
            "metadata": {},
            "source": [
                "## Baseline\n",
                "Add preprocessing, validation, and model training here.\n",
            ],
        },
        {
            "cell_type": "code",
            "id": "submission-baseline",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# Replace this copy with model predictions.\n",
                "if sample_submission is not None:\n",
                "    output = Path('submission.csv')\n",
                "    sample_submission.to_csv(output, index=False)\n",
                "    print(f'Wrote {output} with shape {sample_submission.shape}')\n",
            ],
        },
    ]
    for note in reversed(competition_notes or []):
        name = note.get("name", "competition-notes")
        source_url = note.get(
            "url", f"https://www.kaggle.com/competitions/{competition}"
        )
        content = sanitize_competition_notes(note.get("content", ""))
        cells.insert(
            1,
            {
                "cell_type": "markdown",
                "id": f"competition-note-{len(cells)}",
                "metadata": {"kgnite_note_page": name},
                "source": [
                    f"## Competition notes: {name}\n\n",
                    f"Source: [Kaggle competition page]({source_url})\n\n",
                    content,
                ],
            },
        )
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3"},
            "kgnite": {"competition": competition, "participant": participant},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def write_starter_notebook(
    competition: str,
    output: Path,
    data_dir: Path,
    *,
    participant: str,
    competition_notes: list[dict[str, str]] | None = None,
    kaggle_data_sources: list[str] | None = None,
    force: bool = False,
) -> Path:
    output = output.expanduser().resolve()
    if output.exists() and not force:
        raise FileExistsError(f"Notebook already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    columns = discover_sample_columns(data_dir.expanduser().resolve())
    notebook = starter_notebook(
        competition,
        str(data_dir.expanduser().resolve()),
        columns,
        participant=participant,
        competition_notes=competition_notes,
        kaggle_data_sources=kaggle_data_sources,
    )
    output.write_text(json.dumps(notebook, indent=2) + "\n")
    return output


def _first(row: dict[str, Any], keys: Iterable[str]) -> Any:
    lower = {key.casefold(): value for key, value in row.items()}
    for key in keys:
        value = lower.get(key.casefold())
        if value not in (None, ""):
            return value
    return None


def normalize_scores(
    rows: list[dict[str, Any]], competition: str
) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        raw_score = _first(row, SCORE_KEYS)
        if raw_score in (None, ""):
            continue
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue
        normalized.append(
            {
                "competition": competition,
                "date": str(_first(row, DATE_KEYS) or ""),
                "score": score,
                "public_score": _first(row, ("publicScore",)),
                "private_score": _first(row, ("privateScore",)),
                "description": str(
                    _first(row, ("description", "message", "fileName", "ref")) or ""
                ),
            }
        )
    return normalized


def merge_score_history(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in [*existing, *incoming]:
        key = (
            row.get("competition"),
            row.get("date"),
            row.get("score"),
            row.get("description"),
        )
        merged[key] = row
    return sorted(merged.values(), key=lambda row: str(row.get("date", "")))


def load_score_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("Score history must be a JSON array")
    return data


def save_score_history(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2) + "\n")


def score_sparkline(scores: list[float]) -> str:
    if not scores:
        return ""
    blocks = "▁▂▃▄▅▆▇█"
    low, high = min(scores), max(scores)
    if math.isclose(low, high):
        return blocks[len(blocks) // 2] * len(scores)
    return "".join(
        blocks[round((score - low) / (high - low) * (len(blocks) - 1))]
        for score in scores
    )
