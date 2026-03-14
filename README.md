# kgtool

`kgtool` is a Python CLI that combines:

- `kaggle` CLI for search, metadata, file listing, competition actions, and notebook source pulls
- `kagglehub` for dataset, competition, model, notebook-output downloads, and direct Python-side uploads

## Install

Homebrew Python on macOS usually blocks global `pip install` with PEP 668, so use a virtualenv:

```bash
cd /Users/rajeshsingh/myprojects/kgtool
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Then verify:

```bash
kgtool --help
kgtool doctor
```

## Authentication

You can keep using `KAGGLE_API_TOKEN`.

That is the recommended auth path for your current machine because:

- your Kaggle CLI is configured for `ACCESS_TOKEN`
- `kagglehub` can detect and use `KAGGLE_API_TOKEN`
- you do not currently need `~/.kaggle/kaggle.json` for this tool

Compatibility fallback options still exist:

1. `KAGGLE_API_TOKEN`
2. `~/.kaggle/kaggle.json`
3. `KAGGLE_USERNAME` + `KAGGLE_KEY`

Run:

```bash
kgtool doctor
kgtool doctor --json
```

## Built-in Help

Top-level help:

```bash
kgtool --help
kgtool
```

Usage examples only:

```bash
kgtool usage
```

Command-specific help:

```bash
kgtool search --help
kgtool info --help
kgtool download --help
kgtool submit --help
kgtool browse --help
```

If you run a command without a required argument, `kgtool` now prints the command usage plus concrete examples for that specific command.

## Command Usage

### 1. Environment and Auth

```bash
kgtool doctor
kgtool doctor --json
kgtool usage
```

### 2. Search

Supported resource groups:

- `datasets`
- `competitions`
- `kernels`
- `models`

Examples:

```bash
kgtool search datasets "vision transformer" --sort-by votes
kgtool search competitions llm --category playground --page-size 20
kgtool search kernels rag --language python --kernel-type notebook
kgtool search models gemma --owner google
kgtool search datasets titanic --json
```

### 3. Inspect Info

Supported resource types:

- `dataset`
- `competition`
- `notebook`
- `model`

Examples:

```bash
kgtool info dataset zillow/zecon
kgtool info competition titanic
kgtool info notebook kaggle/getting-started-with-ai4code
kgtool info model google/gemma/pytorch/2b
kgtool info model google/gemma/pytorch/2b/3
kgtool info dataset heptapod/titanic --json
```

Notes:

- `info dataset` downloads metadata plus file listing.
- `info competition` shows competition files.
- `info notebook` shows notebook status and output files.
- `info model` works for base model, variation, or version handles.

### 4. List Files

```bash
kgtool files dataset zillow/zecon
kgtool files competition titanic
kgtool files notebook kaggle/getting-started-with-ai4code
kgtool files model google/gemma/pytorch/2b/3
kgtool files competition titanic --json
```

### 5. Download Assets

Supported download targets:

- `dataset`
- `competition`
- `model`
- `notebook-output`

Examples:

```bash
kgtool download dataset zillow/zecon --output-dir ./downloads
kgtool download dataset zillow/zecon --path data.csv --output-dir ./downloads
kgtool download competition titanic --output-dir ./downloads
kgtool download model google/gemma/pytorch/2b/3 --output-dir ./models
kgtool download notebook-output kaggle/getting-started-with-ai4code --output-dir ./nb-output
```

### 6. Pull Notebook Source

Notebook source and notebook outputs are different operations.

```bash
kgtool pull-notebook kaggle/getting-started-with-ai4code --output-dir ./notebooks
```

### 7. Competition Submissions

File submission:

```bash
kgtool submit titanic --file ./submission.csv --message "baseline v1"
```

Code-competition notebook submission:

```bash
kgtool submit some-code-competition \
  --kernel yourname/your-notebook \
  --version 3 \
  --message "submit notebook version 3"
```

View submissions:

```bash
kgtool submissions titanic
kgtool submissions titanic --json
```

View leaderboard:

```bash
kgtool leaderboard titanic --show
kgtool leaderboard titanic --show --page-size 50
kgtool leaderboard titanic --download --output-dir ./leaderboards
```

### 8. Dataset Uploads

Two modes are supported.

Mode A: `kagglehub` handle-driven upload

```bash
kgtool upload-dataset ./my-dataset \
  --handle yourname/my-dataset \
  --message "initial upload"
```

Mode B: Kaggle CLI metadata-folder upload

```bash
kgtool upload-dataset ./my-dataset --public
kgtool upload-dataset ./my-dataset --version --message "new rows for march"
```

Notes:

- Handle-driven mode is simpler when you already know the target dataset handle.
- CLI mode expects the Kaggle dataset metadata file inside the folder.

### 9. Model Uploads

Two modes are supported.

Mode A: `kagglehub` variation upload

```bash
kgtool upload-model ./my-model \
  --handle yourname/my-model/pytorch/base \
  --license-name Apache-2.0 \
  --message "initial model version"
```

Mode B: Kaggle CLI metadata-folder mode

```bash
kgtool upload-model ./my-model --action create
kgtool upload-model ./my-model --action update
```

Notes:

- `kagglehub` upload is best when you want a direct Python-side upload API.
- CLI mode expects model metadata files in the folder.

### 10. Interactive Browse Workflow

Run:

```bash
kgtool browse
```

Optional shortcuts:

```bash
kgtool browse --resource datasets --search titanic
kgtool browse --resource kernels --search rag --output-dir ./tmp
```

What it does:

1. Prompts for a resource type and search query.
2. Shows a numbered result table.
3. Lets you pick one result.
4. Lets you run one action:
   - `info`
   - `files`
   - `download`
   - `download-output` for notebooks
   - `pull-source` for notebooks

When `browse` starts, it prints a short guide showing what kind of values to enter next. If you exit or send an empty search query, it returns with a hint instead of crashing.

## Design Notes

- Search/list/info actions mainly wrap the Kaggle CLI because it exposes richer discovery features.
- Download actions use `kagglehub` because it gives cleaner direct-download behavior in Python.
- Notebook source pulls and notebook output downloads stay separate because Kaggle separates those concepts too.

## Current Limits

- `browse` is intentionally simple and terminal-based; it is not a full TUI.
- `upload-model` CLI mode only wraps model create/update metadata workflows, while direct artifact upload is handled by `kagglehub`.
- Model downloads are most reliable with full variation-version handles like `<owner>/<model>/<framework>/<variation>/<version>`.
