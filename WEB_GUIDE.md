# kgnite Web Workstation Guide

The kgnite web workstation provides a browser interface for the local `kgnite` CLI. It runs only on your workstation, uses your existing Kaggle credentials, and reads or writes paths relative to the directory where you launch it.

## Start and stop

Start the workstation and open the default browser:

```bash
kgnite web
```

Useful alternatives:

```bash
kgnite web --port 8765
kgnite web --no-browser
kgnite web --heartbeat-timeout 60
kgnite web --command-timeout 900
```

Close the workstation page to stop the server after the heartbeat grace period. Press `Ctrl+C` in the terminal for immediate shutdown.

## Before using Kaggle features

Configure Kaggle authentication, then open the **System** page and run **Diagnostics**. The result should show that the Kaggle CLI and credentials are available.

```bash
export KAGGLE_API_TOKEN="your_token_here"
kgnite web
```

## Search queries versus resource handles

This distinction is important:

- A **query** is general text used for discovery, such as `employee`, `fraud detection`, or `vision transformer`.
- A **handle** uniquely identifies a Kaggle resource and is copied from the `ref` column of search results.

Examples:

| Resource | Query example | Handle example |
|---|---|---|
| Dataset | `employee` | `tawfikelmetwally/employee-dataset` |
| Competition | `titanic` | `titanic` |
| Notebook | `house prices` | `username/notebook-slug` |
| Model | `gemma` | `google/gemma` or a full version handle |

Use queries on **Discover**. Use handles for **Inspect**, **Files**, **Download**, and **Pull notebook source**.

## Discover page

### Search Kaggle

1. Select `datasets`, `competitions`, `kernels`, or `models`.
2. Enter a query.
3. Optionally provide a sort order, tags, or keywords.
4. Open **Resource-specific filters and pagination** when needed.
5. Select **Search**.

Example: employee datasets

```text
Resource: datasets
Query: employee
Sort by: votes
Tags: tabular
Keywords: attrition
```

Copy the required resource's `ref` value from the result table before moving to the Resources page.

Resource-specific filters only affect relevant types. For example, `owner` applies to models, `user` applies to datasets and kernels, while language and kernel type apply to kernels.

### Trending resources

Choose **popular** to rank by activity or **new** to prioritize recently created or updated resources.

Example:

```text
Resource: kernels
Order: new
Search: transformer
Keywords: pytorch
Limit: 20
```

## Competition page

The **Settings** page controls the persistent workspace root, competition and project subfolders, Kaggle username, and default dataset license. The **Projects** page creates generic Kaggle-ready projects with dataset, notebook, and model sources.

Each generated workspace includes its own `README.md`. Use it as the workspace-specific reference for folder purpose, commands, web actions, publishing, and troubleshooting.

### Set up a competition

The setup workflow creates `.<competition-slug>-config.json` plus `data`, `notebooks`, and `submissions` directories.

```text
Competition: titanic
Workspace directory: ./titanic
Metric: accuracy
Lower score is better: unchecked
Download data: checked
Generate notebook: checked
```

Competition data download is enabled by default. Clear it only when you intentionally want an empty local `data/` directory and plan to run solely against Kaggle-mounted data.

Select **Replace an existing generated workspace** only when overwriting generated files is intentional.

### Generate a notebook

Generate a standalone starter notebook for an existing competition directory:

```text
Competition: titanic
Participant: Your Name
Data directory: ./titanic/data
Output notebook: ./titanic/notebooks/titanic-02.ipynb
Include official competition notes: checked
Notes pages: data-description, evaluation
```

The notebook identifies the participant and describes itself as a personal competition workspace. Official notes are fetched through Kaggle's competition-pages API, linked to their source, sanitized, and embedded as rendered Markdown/HTML. The default page is `data-description`; add `evaluation` or `rules` when useful. If a sample-submission CSV exists, its columns are included in the notebook guidance.

### Track performance

Enter the competition slug and keep **Sync from Kaggle** selected to fetch current submissions. Use **Lower score is better** for error or loss metrics.

```text
Competition: titanic
History file: ./titanic/scores.json
Sync from Kaggle: checked
```

Clear **Sync from Kaggle** to view existing local history without making a network request.

### Submit results

For a file-based competition, enter the submission path or use the optional file picker, then leave notebook fields empty. Picked files use session-scoped temporary storage that is removed when the web session ends:

```text
Competition: titanic
Submission file: ./titanic/submissions/submission.csv
Message: random forest baseline
```

For a code competition, provide a notebook handle and version instead:

```text
Competition: code-competition-slug
Notebook handle: username/notebook-slug
Notebook version: 3
Message: notebook version 3
```

The browser asks for confirmation before sending a submission.

### Prepare and publish a showcase notebook

On **Uploads**, use **Prepare Kaggle notebook** to copy an `.ipynb` into a project-local `kaggle-notebooks/<slug>` bundle and generate `kernel-metadata.json`. Enter the notebook title; kgnite derives the Kaggle slug from that title so the metadata ID matches Kaggle's URL behavior. Add a Kaggle handle only when you need to choose a different owner. Preparation is local only. Review the bundle, then use **Push Kaggle notebook**; publishing requires a separate confirmation.

The preparation form supports `dataset_sources`, `competition_sources`, `kernel_sources`, and `model_sources`. Supplying a local dataset directory plus a Kaggle dataset handle also creates a `kaggle-datasets/<slug>` bundle. On push, select **Push staged local datasets first**; choose **version** instead of **create** after that dataset already exists on Kaggle.

## Resources page

### Inspect metadata or list files

Use a handle copied from Discover results:

```text
Action: List files
Type: dataset
Resource handle: tawfikelmetwally/employee-dataset
```

For paginated competition or model file lists, provide page size and the page token returned by the previous request.

### Download

Download an entire resource:

```text
Type: dataset
Resource handle: tawfikelmetwally/employee-dataset
Output directory: ./downloads/employees
```

Provide **Remote file path** to download only one file. Enable **Force fresh download** to bypass cached content.

### Preview dataset rows

Preview reports the file's shape, all detected column names, displayed dimensions, and sample rows. It supports three source types:

- **Kaggle dataset** using `owner/dataset` and an optional Kaggle file path;
- **Absolute local path** such as `/Users/me/data/employees.csv`;
- **Remote URL** using `http://` or `https://`.

```text
Dataset handle: tawfikelmetwally/employee-dataset
Remote file path: Employee.csv
Rows: 10
Columns: all
Maximum file size: 25 MB
```

Use a number such as `10` to display the first ten columns, or `all` to display every column. Increase rows to any positive value. Leave the Kaggle remote path empty to let kgnite select a small CSV, TSV, JSON, JSONL, NDJSON, or text file.

Local files must use absolute paths. URL content is streamed only up to the size guard. Kaggle transfers the selected file in full, not the complete dataset, so the guard also prevents unexpectedly large previews.

### Pull notebook source

Notebook source is different from notebook output:

```text
Notebook handle: username/notebook-slug
Output directory: ./notebooks
```

Use Download with type `notebook-output` when you need the files produced by a notebook run.

### Submissions and leaderboard

Use **My submissions** to inspect your entries. Use **Leaderboard** without a download directory to display rows; provide a directory to download the leaderboard file.

## Uploads page

Uploads change data on Kaggle and always show a confirmation prompt.

### Upload a dataset

Direct KaggleHub mode:

```text
Local directory: ./my-dataset
Dataset handle: username/my-dataset
Message: initial version
Ignore patterns: .DS_Store, *.tmp
```

Leave the handle empty for Kaggle CLI metadata-folder mode. Select **Create a new version** when updating an existing dataset.

### Upload a model

Direct KaggleHub mode:

```text
Local directory: ./my-model
Model handle: username/model-name/pytorch/base
Message: initial model version
License: Apache-2.0
```

Leave the handle empty and select `create` or `update` for Kaggle CLI metadata mode.

## System page

- **Diagnostics** checks the Kaggle CLI, KaggleHub, credentials, and runtime.
- **Usage guide** displays built-in CLI workflow examples.
- **Shell completion script** safely prints Bash or Zsh completion definitions. It does not modify shell files from the browser.
- The CLI `browse` workflow is represented by the browser-native Discover and Resources pages.

To install or refresh completions on the current workstation, run this in a terminal:

```bash
kgnite completions
```

Run it again after upgrading or reinstalling `kgnite`; it rewrites the completion file under `~/.local/share/kgnite/completions` and prints the line to add to `~/.zshrc` or `~/.bashrc`. On another workstation, install or update `kgnite` there first, then run the same command.

## Advanced page

Use the advanced runner for uncommon non-interactive option combinations:

```text
kgnite search kernels rag --language python --kernel-type notebook --json
```

The command is parsed into arguments and is never passed through a shell. Recursive `web` launch and terminal-interactive `browse` are blocked. Completion access requires `completions --print`.

## Table and JSON results

Row-based results open in **Table** view by default. Wide tables retain readable column widths instead of compressing headers. Use the horizontal scrollbar, a trackpad gesture, or focus the table region for keyboard scrolling to reach columns beyond the page width. Column headers remain visible while scrolling vertically.

Select **JSON** when you need raw field names, nested values, or copyable machine-readable output. Commands that return plain text automatically use a text panel.

## Local paths and working directory

The header displays the active workspace. Relative paths such as `./downloads` and `./notebooks` resolve from that directory.

For predictable paths:

```bash
cd ~/kaggle-work
kgnite web
```

## Troubleshooting

### A request returns 401 or 403

Run Diagnostics. Confirm authentication and competition-rule acceptance. Also confirm that you entered a handle rather than a search query.

### A new feature is missing

Close the running session, reinstall the current project, then launch again:

```bash
"$HOME/.local/share/kgnite/venv/bin/pip" install --no-deps --force-reinstall .
kgnite web
```

### A command times out

Restart with a larger command timeout:

```bash
kgnite web --command-timeout 1800
```

### The browser does not open

Use `kgnite web --no-browser` and copy the printed localhost URL into a browser on the same workstation.

## Security model

- The server binds only to `127.0.0.1`.
- API requests require a random per-session token.
- Commands run without a shell.
- Browser values from Kaggle are rendered as text, not executable HTML.
- Closing the page stops heartbeats and ends the temporary server session.
