# kgnite

`kgnite` is a practical command-line companion for Kaggle. It brings resource discovery, downloads, uploads, competition setup, notebook generation, submissions, and score tracking into one consistent CLI.

New to the browser interface? Read the [kgnite Web Workstation Guide](WEB_GUIDE.md) for page-by-page instructions and practical examples.

It uses:

- the Kaggle CLI for search, metadata, file listings, notebook source, and competition actions;
- `kagglehub` for downloads and handle-based dataset/model uploads;
- local JSON files for competition workspace configuration and score history.

## Contents

- [Requirements](#requirements)
- [Authentication](#authentication)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Local web application](#local-web-application)
- [Competition workflow](#competition-workflow)
- [Finding Kaggle resources](#finding-kaggle-resources)
- [Complete command reference](#complete-command-reference)
- [Shell completions](#shell-completions)
- [Maintenance and development](#maintenance-and-development)
- [Troubleshooting](#troubleshooting)

## Requirements

- Python 3.11 or newer
- Kaggle CLI available as `kaggle`
- internet access for Kaggle operations
- valid Kaggle credentials

Confirm the prerequisites:

```bash
python3 --version
kaggle --version
kaggle config view
```

## Authentication

The recommended method is a Kaggle API token:

```bash
export KAGGLE_API_TOKEN="your_token_here"
```

To persist it in Zsh:

```bash
echo 'export KAGGLE_API_TOKEN="your_token_here"' >> ~/.zshrc
source ~/.zshrc
```

The following legacy methods are also supported:

- `~/.kaggle/kaggle.json`
- `KAGGLE_USERNAME` together with `KAGGLE_KEY`

If using `kaggle.json`, protect it:

```bash
chmod 600 ~/.kaggle/kaggle.json
```

Ask `kgnite` what it detects:

```bash
kgnite doctor
kgnite doctor --json
```

`doctor` reports tool availability and authentication state without displaying credential values.

## Installation

### Recommended: user-local installation

From the repository root:

```bash
cd /path/to/kgnite
KGNITE_BIN_DIR="$HOME/.local/bin" bash scripts/install.sh
```

This method does not require `sudo`. The installer creates an isolated Python environment under `~/.local/share/kgnite` and places the `kgnite` launcher in `~/.local/bin`.

Ensure `~/.local/bin` is at the beginning of your `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
hash -r
```

For Zsh, persist it with:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
hash -r
```

For Bash, add the same export to `~/.bashrc` instead.

### System-wide launcher

If you intentionally want the launcher in `/usr/local/bin`, run:

```bash
cd /path/to/kgnite
bash scripts/install.sh
```

The installer creates the isolated environment and attempts to copy the launcher to `/usr/local/bin/kgnite`. If that directory is not writable, it prints a command similar to:

```bash
sudo install -m 755 "$HOME/.local/share/kgnite/kgnite-launcher" /usr/local/bin/kgnite
```

Run only the exact command printed for your workstation.

### Refresh an existing installation

If `kgnite` works but newly added commands such as `web`, `setup`, or `performance` are missing, your shell is using an older installed copy. Refresh the isolated installation directly from the current source tree:

```bash
cd /path/to/kgnite

"$HOME/.local/share/kgnite/venv/bin/pip" \
  install --upgrade --force-reinstall .

hash -r
```

The `/usr/local/bin/kgnite` launcher created by this project points to that same isolated environment, so it normally does not need to be recreated. If you instead installed a user-local launcher, ensure `~/.local/bin` precedes `/usr/local/bin` in `PATH`.

To diagnose which copy is running:

```bash
command -v kgnite
which -a kgnite
```

Expected locations are usually one of:

```text
~/.local/bin/kgnite
/usr/local/bin/kgnite
```

If multiple copies are listed, the first one is the command your shell uses.

### Development installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Verify the installation

```bash
command -v kgnite
kgnite --help
kgnite doctor
kgnite setup --help
kgnite performance --help
kgnite trending --help
kgnite web --help
kgnite completions
```

The top-level help should include at least these newer commands:

```text
setup
template
performance
trending
web
```

Finally, launch the browser application:

```bash
kgnite web
```

If the command still shows an older feature set, rerun the [existing-install refresh](#refresh-an-existing-installation) and inspect `which -a kgnite` for another launcher earlier in `PATH`.

## Quick start

```bash
# Search and inspect resources
kgnite search datasets "house prices" --sort-by votes
kgnite info dataset zillow/zecon
kgnite files competition titanic

# Download a resource
kgnite download dataset zillow/zecon --output-dir ./downloads

# Preview limited rows from one dataset file
kgnite preview dataset tawfikelmetwally/employee-dataset --rows 10

# Start a competition workspace
kgnite setup titanic --directory ./titanic

# Submit and track results
kgnite submit titanic --file ./submission.csv --message "baseline"
kgnite performance titanic --sync

# Discover currently popular resources
kgnite trending kernels --tag python --limit 20

# Open the local web application
kgnite web
```

Run `kgnite` with no arguments for top-level help, or append `--help` to any command:

```bash
kgnite search --help
kgnite setup --help
```

## Local web application

Launch the workstation UI in your default browser:

```bash
kgnite web
```

Select **Web guide & examples** in the workstation header at any time. It opens a browser-friendly guide in a separate tab while preserving the active local session. The same material is available in [WEB_GUIDE.md](WEB_GUIDE.md).

The web application provides forms for:

- resource search, trending discovery, tags, keywords, resource-specific filters, sorting, and pagination;
- competition workspace setup, overwrite controls, and starter-notebook generation;
- score synchronization and performance visualization;
- file and notebook-version submissions;
- leaderboards, submission history, resource inspection, and paginated file listings;
- complete or single-file downloads with cache-refresh controls;
- notebook-source pulls;
- dataset and model uploads, including KaggleHub and metadata-folder modes;
- runtime diagnostics, usage examples, and read-only shell-completion output;
- an advanced command runner for other non-interactive option combinations.

The web navigation maps the CLI into these pages:

| Web page | CLI capabilities |
|---|---|
| Discover | `search`, `trending`, and the discovery portion of `browse` |
| Competition | `setup`, `template`, `performance`, `submit` |
| Resources | `info`, `files`, `preview`, `download`, `pull-notebook`, `leaderboard`, `submissions` |
| Uploads | `upload-dataset`, `upload-model` |
| System | `doctor`, `usage`, and safe `completions --print` output |
| Advanced | Allowlisted non-interactive commands and uncommon option combinations |

The `web` command is not recursively available inside its own session. The terminal-interactive `browse` command is represented by the browser-native Discover and Resources pages. Completion installation is intentionally not performed from the web session; the System page can print a completion script without changing shell files.

Commands run on your workstation, in the directory where `kgnite web` was launched, using your existing Kaggle credentials. Paths entered in the UI are therefore local workstation paths.

The server binds only to `127.0.0.1`, uses a random available port by default, and protects API calls with a per-session token. It is not exposed to other computers on the network.

The page sends a local heartbeat while open. After the page is closed and heartbeats stop, the server shuts down automatically. Shutdown allows a 30-second grace period to avoid ending the session during a brief page reload. Press `Ctrl+C` in the launching terminal for immediate shutdown.

Useful launch options:

```bash
# Use a predictable local port
kgnite web --port 8765

# Print the URL without opening a browser
kgnite web --no-browser

# End the server sooner after the page closes
kgnite web --heartbeat-timeout 10

# Allow long downloads or uploads up to 15 minutes
kgnite web --command-timeout 900
```

The advanced runner parses command arguments without invoking a shell. `web`, interactive `browse`, and completion installation are intentionally unavailable through it.

## Competition workflow

### 1. Create a workspace

```bash
kgnite setup titanic --directory ./titanic
```

Interactive mode asks for the competition, metric direction, whether to download data, and whether to generate a notebook. The resulting structure is:

```text
titanic/
├── .kgnite.json
├── data/
├── notebooks/
│   └── starter.ipynb
└── submissions/
```

For scripts or CI, provide explicit choices:

```bash
kgnite setup titanic \
  --directory ./titanic \
  --metric accuracy \
  --no-lower-is-better \
  --download \
  --template
```

Use `--lower-is-better` for loss/error metrics and `--no-lower-is-better` for accuracy, AUC, F1, and similar metrics. `--force` permits generated files to be replaced and downloads to be refreshed.

### 2. Generate or regenerate a notebook

```bash
kgnite template titanic \
  --data-dir ./titanic/data \
  --output ./titanic/notebooks/starter.ipynb
```

The generated notebook discovers train, test, and sample-submission CSV files. When a sample submission is already available, its columns are documented in the notebook. Use `--force` only when replacing an existing notebook is intentional.

### 3. Submit a result

File-based competition:

```bash
kgnite submit titanic \
  --file ./titanic/submissions/submission.csv \
  --message "random forest baseline"
```

Code competition:

```bash
kgnite submit my-code-competition \
  --kernel my-user/my-notebook \
  --version 3 \
  --message "notebook version 3"
```

### 4. Track performance

Fetch current submissions, merge them into local history, and show a score sparkline:

```bash
kgnite performance titanic --sync
```

By default, history is stored in `.kgnite/<competition>-scores.json`. To use a different file or a lower-is-better metric:

```bash
kgnite performance titanic \
  --sync \
  --history ./titanic/scores.json \
  --lower-is-better
```

Without `--sync`, the command reads and visualizes existing local history without contacting Kaggle.

## Finding Kaggle resources

### Search

```bash
kgnite search datasets housing --tag tabular --keyword csv
kgnite search kernels rag --language python --kernel-type notebook
kgnite search competitions llm --category playground
kgnite search models gemma --owner google
```

Repeated `--tag` and `--keyword` values are combined: every supplied value must appear somewhere in the returned row metadata.

Options only apply to relevant resources:

| Option | Applicable resources | Use it when |
|---|---|---|
| `--owner` | models | restricting models to an owner |
| `--user` | datasets, kernels | restricting results to a Kaggle user |
| `--category` | competitions | selecting a competition category |
| `--group` | competitions | selecting general, entered, or in-class competitions |
| `--language` | kernels | selecting Python, R, SQLite, or Julia |
| `--kernel-type` | kernels | selecting scripts or notebooks |
| `--output-type` | kernels | selecting visualization or data outputs |
| `--dataset` | kernels | finding notebooks attached to a dataset |
| `--competition` | kernels | finding notebooks attached to a competition |

Common sort values accepted by Kaggle include:

| Resource | Useful `--sort-by` values |
|---|---|
| datasets | `hottest`, `votes`, `updated`, `active` |
| competitions | `grouped`, `prize`, `earliestDeadline`, `latestDeadline`, `numberOfTeams`, `recentlyCreated` |
| kernels | `hotness`, `commentCount`, `dateCreated`, `dateRun`, `relevance`, `viewCount`, `voteCount` |
| models | `hotness`, `downloadCount`, `voteCount`, `notebookCount`, `createTime` |

### Trending and newly added resources

```bash
kgnite trending datasets --order popular
kgnite trending datasets --order new --limit 25
kgnite trending competitions --category playground
kgnite trending kernels --search transformer --tag python --keyword pytorch
```

`trending` chooses the appropriate Kaggle sort order for each resource type. `--order popular` is the default; `--order new` prioritizes recently created or updated resources.

### Interactive browsing

```bash
kgnite browse
kgnite browse --resource datasets --search titanic --limit 15
```

The browser guides you through resource selection, search results, and actions such as info, file listing, download, notebook-output download, or notebook-source pull.

## Complete command reference

General syntax:

```text
kgnite <command> [arguments] [options]
```

Most data-returning commands support `--json`. Use it for scripts, pipelines, and machine-readable output.

### `usage`

Print common workflow examples.

```bash
kgnite usage
```

### `doctor`

Inspect Kaggle CLI, `kagglehub`, and authentication state.

```text
kgnite doctor [--json]
```

| Option | When to use it |
|---|---|
| `--json` | Consume the diagnostic result from a script. |

### `completions`

Install or print Bash/Zsh completion definitions.

```text
kgnite completions [--shell {bash,zsh}] [--print] [--json]
```

| Option | When to use it |
|---|---|
| `--shell bash` / `--shell zsh` | Override automatic `$SHELL` detection. |
| `--print` | Print the completion script instead of installing it. |
| `--json` | Return installation details as JSON. |

### `web`

Launch a temporary localhost web application and, by default, open it in the system browser.

```text
kgnite web [--port NUMBER] [--browser | --no-browser]
           [--heartbeat-timeout SECONDS] [--command-timeout SECONDS]
```

| Option | When to use it |
|---|---|
| `--port NUMBER` | Use a known localhost port; `0` selects an available port automatically. |
| `--browser` | Open the system default browser; this is the default. |
| `--no-browser` | Print the local URL for manual opening or headless workstation use. |
| `--heartbeat-timeout SECONDS` | Change how long the server waits after page heartbeats stop; minimum 5, default 30. |
| `--command-timeout SECONDS` | Limit each browser-triggered command; default 300 seconds. Increase for large transfers. |

Only localhost binding is supported by design. Closing the page ends the server after the heartbeat timeout; `Ctrl+C` ends it immediately.

### `search`

Search datasets, competitions, kernels, or models.

```text
kgnite search {datasets,competitions,kernels,models} [search] [options]
```

| Option | When to use it |
|---|---|
| `--sort-by VALUE` | Change Kaggle's result ordering. |
| `--page NUMBER` | Request a result page for datasets, competitions, or kernels. |
| `--page-size NUMBER` | Set page size for competitions, kernels, or models. |
| `--owner OWNER` | Filter models by owner. |
| `--user USER` | Filter datasets or kernels by user. |
| `--category CATEGORY` | Filter competitions by category. |
| `--group GROUP` | Filter competitions by group. |
| `--language LANGUAGE` | Filter kernels by language. |
| `--kernel-type TYPE` | Filter kernel type, such as `script` or `notebook`. |
| `--output-type TYPE` | Filter kernel output type. |
| `--dataset HANDLE` | Find kernels associated with a dataset. |
| `--competition SLUG` | Find kernels associated with a competition. |
| `--tag TAG` | Require a returned metadata tag; repeat as needed. |
| `--keyword WORD` | Require a metadata keyword; repeat as needed. |
| `--json` | Print the rows as JSON. |

### `setup`

Create a local competition workspace.

```text
kgnite setup [competition] [options]
```

| Option | When to use it |
|---|---|
| `--directory PATH` | Choose the workspace path; defaults to the competition slug. |
| `--metric NAME` | Record the competition metric in `.kgnite.json`. |
| `--lower-is-better` | Mark loss/error-style metrics. |
| `--no-lower-is-better` | Mark score-style metrics where higher is better. |
| `--download` / `--no-download` | Explicitly enable or skip the data download. |
| `--template` / `--no-template` | Explicitly enable or skip starter-notebook creation. |
| `--force` | Replace generated files and refresh downloads. |
| `--json` | Use non-interactive defaults and return workspace details as JSON. |

### `template`

Generate a starter Jupyter notebook.

```text
kgnite template COMPETITION [--output PATH] [--data-dir PATH] [--force] [--json]
```

| Option | When to use it |
|---|---|
| `--output PATH` | Choose the notebook filename. |
| `--data-dir PATH` | Point generated code at the competition data directory; defaults to `./data`. |
| `--force` | Intentionally overwrite an existing notebook. |
| `--json` | Return the generated path as JSON. |

### `performance`

Persist and visualize submission scores.

```text
kgnite performance COMPETITION [--sync] [--history PATH] [--lower-is-better] [--json]
```

| Option | When to use it |
|---|---|
| `--sync` | Fetch Kaggle submissions and merge them into history. |
| `--history PATH` | Read/write a custom history file. |
| `--lower-is-better` | Select the minimum score as best. |
| `--json` | Return summary and score history as JSON. |

### `trending`

Show popular or newly added resources.

```text
kgnite trending {datasets,competitions,kernels,models} [options]
```

| Option | When to use it |
|---|---|
| `--order {popular,new}` | Choose popularity or recency; defaults to `popular`. |
| `--search TEXT` | Narrow the upstream Kaggle query. |
| `--tag TAG` | Require a tag; repeat as needed. |
| `--keyword WORD` | Require a keyword; repeat as needed. |
| `--category CATEGORY` | Restrict competitions to a category. |
| `--limit NUMBER` | Limit displayed rows; defaults to 10. |
| `--json` | Print rows as JSON. |

### `info`

Show resource metadata and related files.

```text
kgnite info {dataset,competition,notebook,model} HANDLE [--json]
```

Handle examples:

- dataset: `owner/dataset`
- competition: `competition-slug`
- notebook: `owner/notebook`
- model: `owner/model`, `owner/model/framework/variation`, or a versioned five-part handle

Use `--json` for machine-readable metadata.

### `files`

List files belonging to a resource.

```text
kgnite files {dataset,competition,notebook,model} HANDLE [options]
```

| Option | When to use it |
|---|---|
| `--page-size NUMBER` | Set the result size for paginated competition/model listings. |
| `--page-token TOKEN` | Continue a paginated competition/model listing. |
| `--json` | Print file rows as JSON. |

Model file listing requires a version handle such as `owner/model/framework/variation/version`.

### `download`

Download with `kagglehub`.

```text
kgnite download {dataset,competition,model,notebook-output} HANDLE [options]
```

| Option | When to use it |
|---|---|
| `--path REMOTE_PATH` | Download one specific file within the resource. |
| `--output-dir PATH` | Choose the destination directory. |
| `--force` | Bypass cached content and download again. |
| `--json` | Return the resolved download path as JSON. |

Notebook source is not a notebook output. Use `pull-notebook` for source code.

### `preview`

Preview shape, column names, and limited rows from a Kaggle dataset file, absolute local workstation path, or HTTP/HTTPS URL.

```text
kgnite preview dataset OWNER/DATASET [options]
kgnite preview local /ABSOLUTE/PATH/FILE.csv [options]
kgnite preview url https://example.com/file.csv [options]
```

| Option | When to use it |
|---|---|
| `--path REMOTE_PATH` | Choose a specific CSV, TSV, JSON, JSONL, NDJSON, or text file. Without it, kgnite selects a small previewable file. |
| `--rows NUMBER` | Limit displayed records; defaults to 10. |
| `--columns NUMBER` | Limit displayed columns; defaults to 10. |
| `--columns all` | Display every detected column while retaining the row limit. |
| `--max-file-size-mb NUMBER` | Refuse unexpectedly large files; defaults to 25 MB. |
| `--force` | Refresh the selected file instead of using cached content. |
| `--json` | Return file metadata and preview rows as JSON. |

Every result reports total shape, all detected column names, displayed dimensions, and sample rows. Kaggle preview fetches only the selected file into temporary storage; it does not download the complete dataset. URL preview streams at most the configured size limit. Local preview requires an absolute path. Because shape calculation scans the selected file, that file must fit within the size guard.

In web mode, wide preview tables keep readable column widths and provide horizontal scrolling rather than squeezing every column into the viewport. A hint above the table reports the number of columns and indicates when to scroll.

Examples:

```bash
kgnite preview dataset tawfikelmetwally/employee-dataset \
  --path Employee.csv --rows 20 --columns all

kgnite preview local "$HOME/data/employees.csv" \
  --rows 50 --columns 10

kgnite preview url https://example.com/employees.csv \
  --rows 10 --columns all --max-file-size-mb 5
```

### `pull-notebook`

Pull notebook source through the Kaggle CLI.

```text
kgnite pull-notebook OWNER/NOTEBOOK [--output-dir PATH] [--json]
```

| Option | When to use it |
|---|---|
| `--output-dir PATH` | Select where source files are written. |
| `--json` | Return Kaggle's result as JSON. |

### `submit`

Submit a file or notebook version to a competition.

```text
kgnite submit COMPETITION (--file PATH | --kernel HANDLE) --message TEXT [options]
```

| Option | When to use it |
|---|---|
| `--file PATH` | Submit a local file. |
| `--kernel HANDLE` | Submit a Kaggle notebook in a code competition. |
| `--version NUMBER` | Select the notebook version used with `--kernel`. |
| `--message TEXT` | Required submission description. |
| `--json` | Return Kaggle's response as JSON. |

Provide either `--file` or `--kernel`. A notebook `--version` is only meaningful with `--kernel`.

### `leaderboard`

Show or download a competition leaderboard.

```text
kgnite leaderboard COMPETITION [options]
```

| Option | When to use it |
|---|---|
| `--show` | Display leaderboard rows in the terminal. This is the default when not downloading. |
| `--download` | Download the leaderboard file. |
| `--output-dir PATH` | Choose where the downloaded leaderboard is saved. |
| `--page-size NUMBER` | Control leaderboard page size. |
| `--page-token TOKEN` | Continue a paginated result. |
| `--json` | Print rows or download details as JSON. |

### `submissions`

List your competition submissions.

```text
kgnite submissions COMPETITION [--json]
```

Kaggle can reject this request if you have not joined the competition, accepted its rules, or made a submission. `kgnite` reports these likely causes when the upstream API returns the common access error.

### `upload-dataset`

Upload a dataset directory.

```text
kgnite upload-dataset LOCAL_DIR [options]
```

| Option | When to use it |
|---|---|
| `--handle OWNER/DATASET` | Use direct `kagglehub` upload mode. |
| `--message TEXT` | Add create/version notes. |
| `--ignore PATTERN ...` | Exclude files in `kagglehub` mode. Place this option after other options because it accepts multiple values. |
| `--version` | Run Kaggle CLI dataset-version mode instead of create mode. |
| `--public` | Make a newly created CLI-mode dataset public. |
| `--keep-tabular` | Keep tabular files in native form in CLI mode. |
| `--dir-mode {skip,zip,tar}` | Choose how CLI mode handles subdirectories. |
| `--delete-old-versions` | Delete old versions during a CLI-mode version upload. |
| `--json` | Return upload details as JSON. |

With `--handle`, `kgnite` uses `kagglehub`. Without it, the local directory must contain metadata expected by the Kaggle CLI.

### `upload-model`

Upload a model directory.

```text
kgnite upload-model LOCAL_DIR [options]
```

| Option | When to use it |
|---|---|
| `--handle OWNER/MODEL/FRAMEWORK/VARIATION` | Use direct `kagglehub` upload mode. |
| `--message TEXT` | Add model version notes. |
| `--license-name NAME` | Set the license when creating through `kagglehub`. |
| `--ignore PATTERN ...` | Exclude files in `kagglehub` mode. Place this option after other options because it accepts multiple values. |
| `--sigstore` | Enable Sigstore signing in `kagglehub` mode. |
| `--action {create,update}` | Choose the Kaggle CLI metadata action; defaults to `create`. |
| `--json` | Return upload details as JSON. |

With `--handle`, `kgnite` uses `kagglehub`. Without it, it uses Kaggle CLI metadata mode.

### `browse`

Run the interactive search, inspect, and download workflow.

```text
kgnite browse [options]
```

| Option | When to use it |
|---|---|
| `--resource {datasets,competitions,kernels,models}` | Preselect the resource type. |
| `--search TEXT` | Supply the initial query. |
| `--sort-by VALUE` | Choose Kaggle's search ordering. |
| `--page NUMBER` | Start on a particular page; defaults to 1. |
| `--page-size NUMBER` | Choose the upstream page size; defaults to 20. |
| `--limit NUMBER` | Limit rows in the picker; defaults to 10. |
| `--output-dir PATH` | Set the initial download or notebook-pull destination. |

Interactive download choices include the Kaggle cache, current directory, or a custom directory. Resource-specific subdirectories prevent unrelated downloads from colliding.

## Shell completions

Install completions for the detected shell:

```bash
kgnite completions
```

Or choose a shell explicitly:

```bash
kgnite completions --shell zsh
kgnite completions --shell bash
```

Generated files are stored under `~/.local/share/kgnite/completions`. The command prints the exact lines needed to enable completion immediately and persist it in your shell configuration. Run it again after upgrading `kgnite`.

## Maintenance and development

Reinstall after changing the source:

```bash
"$HOME/.local/share/kgnite/venv/bin/pip" \
  install --upgrade --force-reinstall .
hash -r
```

Alternatively, rerun `scripts/install.sh` with the same `KGNITE_BIN_DIR` used for the original installation.

Run the project checks:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
ruff check src tests
ruff format --check src tests
```

Available Make targets:

```bash
make install
make reinstall
make uninstall
make dev
make completions
```

Uninstall:

```bash
bash scripts/uninstall.sh
```

## Troubleshooting

### New commands are missing after an update

Check the resolved launcher and all duplicates:

```bash
command -v kgnite
which -a kgnite
```

Then refresh the installed environment from the repository root:

```bash
"$HOME/.local/share/kgnite/venv/bin/pip" \
  install --upgrade --force-reinstall .
hash -r
kgnite web --help
```

If `which -a` lists both `~/.local/bin/kgnite` and `/usr/local/bin/kgnite`, ensure the intended directory appears first in `PATH`.

### `No module named kagglesdk.competitions.legacy`

The `kagglesdk` 0.1.32 wheel is missing a package imported by its own competition client. The project excludes that broken release. Reinstall from the repository root so the dependency resolver selects a working SDK version:

```bash
"$HOME/.local/share/kgnite/venv/bin/pip" \
  install --upgrade --force-reinstall .
hash -r
kgnite --help
```

Confirm the resolved version if necessary:

```bash
"$HOME/.local/share/kgnite/venv/bin/pip" show kagglesdk
```

It must not report version `0.1.32`.

### `kaggle` is not installed or not on `PATH`

Install the Kaggle CLI, then confirm `kaggle --version` works in the same shell used for `kgnite`.

### Authentication is missing

Export `KAGGLE_API_TOKEN`, configure `kaggle.json`, and rerun:

```bash
kgnite doctor
```

### Submission history is unavailable

Open the competition page, join the competition, accept its rules, and make at least one submission before retrying `kgnite submissions` or `kgnite performance --sync`.

### A generated file already exists

`setup` and `template` protect existing generated files. Review the file first, then use `--force` only when replacement is intended.

### Model handles fail

Use the full handle required by the operation. Model downloads and file listings are most reliable with a versioned handle:

```text
owner/model/framework/variation/version
```

### JSON output is needed for automation

Use `--json` where supported. In `setup`, JSON mode also avoids optional interactive questions and uses safe defaults unless explicit flags are supplied.

### The web page does not open automatically

Copy the URL printed by `kgnite web` into any local browser, or launch with `kgnite web --no-browser`. If a selected port is occupied, omit `--port` to let kgnite choose an available one.

### A web operation times out

Large downloads and uploads can exceed the default five-minute command limit. Restart with a larger value, for example `kgnite web --command-timeout 1800`.
