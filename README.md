# kgnite

`kgnite` is a command-line utility for working with Kaggle datasets, competitions, notebooks, models, downloads, uploads, and competition workflows.

It combines:

- `kaggle` CLI for search, listings, metadata, competition actions, and notebook source pulls
- `kagglehub` for dataset, competition, model, and notebook-output downloads, plus direct Python-side uploads

Quick entry points:

- [QUICKSTART.md](QUICKSTART.md)
- [Makefile](Makefile)
- [completions/kgnite.bash](completions/kgnite.bash)
- [completions/\_kgnite](completions/_kgnite)

## 1. Configure Kaggle First

`kgnite` depends on Kaggle authentication already being available on your machine.

Recommended auth method:

- `KAGGLE_API_TOKEN`

Compatible fallback methods:

- `~/.kaggle/kaggle.json`
- `KAGGLE_USERNAME` + `KAGGLE_KEY`

For this project, `KAGGLE_API_TOKEN` is the preferred option.

### Option A: Use `KAGGLE_API_TOKEN`

Set it in your shell:

```bash
export KAGGLE_API_TOKEN="your_token_here"
```

To make it permanent in `zsh`, add this to `~/.zshrc`:

```bash
export KAGGLE_API_TOKEN="your_token_here"
```

Then reload:

```bash
source ~/.zshrc
```

### Option B: Use Kaggle credentials file

Create:

```bash
~/.kaggle/kaggle.json
```

with contents like:

```json
{
  "username": "your_kaggle_username",
  "key": "your_kaggle_api_key"
}
```

Then secure it:

```bash
chmod 600 ~/.kaggle/kaggle.json
```

### Verify Kaggle setup

Check your Kaggle CLI:

```bash
kaggle --version
kaggle config view
```

Check `kgnite` view of auth:

```bash
kgnite doctor
kgnite doctor --json
```

## 2. Prerequisites

You need:

- Python 3.11+
- Kaggle CLI installed and available on `PATH`
- internet access
- valid Kaggle authentication

Optional but useful:

- `zsh` or `bash`
- `/usr/local/bin` write access if you want system-style installation

## 3. Install kgnite

There are two main ways to install it.

### Option A: Install as a utility command

This is the recommended install for normal use.

From the project root:

```bash
cd /Users/rajeshsingh/myprojects/kgnite
bash scripts/install.sh
```

What this does:

1. Creates an isolated virtualenv in `~/.local/share/kgnite/venv`
2. Installs `kgnite` into that virtualenv
3. Tries to create a launcher at `/usr/local/bin/kgnite`

If `/usr/local/bin` is writable, you are done.

Verify:

```bash
kgnite --help
kgnite doctor
kgnite completions
```

### If `/usr/local/bin` is not writable

The installer prints a follow-up command.

Example:

```bash
sudo install -m 755 "/Users/rajeshsingh/.local/share/kgnite/kgnite-launcher" "/usr/local/bin/kgnite"
```

Then refresh command lookup:

```bash
hash -r
kgnite --help
kgnite completions
```

### Option B: Install without sudo into your own bin directory

If you prefer a user-only install:

```bash
cd /Users/rajeshsingh/myprojects/kgnite
KGNITE_BIN_DIR="$HOME/.local/bin" bash scripts/install.sh
```

Then make sure that directory is in your `PATH`.

For the current shell:

```bash
export PATH="$HOME/.local/bin:$PATH"
hash -r
kgnite --help
kgnite completions
```

To make it permanent in `zsh`, add this to `~/.zshrc`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then reload:

```bash
source ~/.zshrc
hash -r
```

### Option C: Local development install

Use this only if you are actively editing the project:

```bash
cd /Users/rajeshsingh/myprojects/kgnite
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Usage after any install

```
❯ kgnite
usage: kgnite [-h] {usage,completions,doctor,search,info,files,download,pull-notebook,submit,leaderboard,submissions,upload-dataset,upload-model,browse} ...

Unified Kaggle helper for search, metadata, files, downloads, and notebook pulls.

positional arguments:
  {usage,completions,doctor,search,info,files,download,pull-notebook,submit,leaderboard,submissions,upload-dataset,upload-model,browse}
    usage               Show example workflows and common command patterns.
    completions         Install or print shell completion setup.
    doctor              Inspect local Kaggle/KaggleHub availability and authentication state.
    search              Search Kaggle resources.
    info                Show metadata and related information for a resource.
    files               List files for a dataset, competition, notebook, or model version.
    download            Download Kaggle assets using kagglehub.
    pull-notebook       Pull notebook source files via the Kaggle CLI.
    submit              Submit a file or notebook run to a Kaggle competition.
    leaderboard         Show or download a competition leaderboard.
    submissions         List your submissions for a competition.
    upload-dataset      Upload or version a dataset. Use --handle for kagglehub upload, or rely on metadata files for kaggle CLI mode.
    upload-model        Upload a model variation/version. Use --handle for kagglehub upload, or CLI metadata mode for create/update.
    browse              Interactive terminal workflow for search -> inspect -> download.

options:
  -h, --help            show this help message and exit

Common workflows:
  kgnite doctor
  kgnite completions
  kgnite search datasets "vision transformer" --sort-by votes
  kgnite info dataset zillow/zecon
  kgnite files competition titanic
  kgnite download dataset zillow/zecon --output-dir ./downloads
  kgnite pull-notebook owner/notebook --output-dir ./notebooks
  kgnite submit titanic --file ./submission.csv --message "baseline"
  kgnite leaderboard titanic --show
  kgnite upload-dataset ./my-dataset --handle me/my-dataset --message "v1"
  kgnite upload-model ./my-model --handle me/model/pytorch/base --message "v1"
  kgnite browse
```

## 4. First Run

After installation:

```bash
kgnite
kgnite doctor
kgnite usage
kgnite completions
```

Behavior:

- `kgnite` with no arguments prints help and common usage examples
- missing required arguments print command-specific examples
- `kgnite doctor` shows Kaggle auth and runtime status

## 5. Built-in Help

Top-level help:

```bash
kgnite --help
kgnite
```

Examples-only help:

```bash
kgnite usage
```

Command help:

```bash
kgnite search --help
kgnite info --help
kgnite download --help
kgnite completions --help
kgnite submit --help
kgnite browse --help
```

## 6. Shell Completion Workflow

`kgnite` can now manage completions directly.

Run:

```bash
kgnite completions
```

What it does:

1. Detects your shell from `$SHELL`
2. Generates the right completion file for `bash` or `zsh`
3. Writes it to:
   - `~/.local/share/kgnite/completions/kgnite.bash` for Bash
   - `~/.local/share/kgnite/completions/_kgnite` for Zsh
4. Prints the exact command to refresh completions immediately
5. Prints the exact config line(s) to add for persistence

Examples:

```bash
kgnite completions
kgnite completions --shell zsh
kgnite completions --shell bash
kgnite completions --print
```

If you reinstall or update `kgnite`, run `kgnite completions` again to refresh the generated completion file.

## 7. Core Usage

### Search Kaggle resources

Supported groups:

- `datasets`
- `competitions`
- `kernels`
- `models`

Examples:

```bash
kgnite search datasets "vision transformer" --sort-by votes
kgnite search competitions llm --category playground --page-size 20
kgnite search kernels rag --language python --kernel-type notebook
kgnite search models gemma --owner google
kgnite search datasets titanic --json
```

### Inspect metadata and info

Supported resource types:

- `dataset`
- `competition`
- `notebook`
- `model`

Examples:

```bash
kgnite info dataset zillow/zecon
kgnite info competition titanic
kgnite info notebook kaggle/getting-started-with-ai4code
kgnite info model google/gemma/pytorch/2b
kgnite info model google/gemma/pytorch/2b/3
kgnite info dataset heptapod/titanic --json
```

### List files

```bash
kgnite files dataset zillow/zecon
kgnite files competition titanic
kgnite files notebook kaggle/getting-started-with-ai4code
kgnite files model google/gemma/pytorch/2b/3
kgnite files competition titanic --json
```

### Download assets

Supported download targets:

- `dataset`
- `competition`
- `model`
- `notebook-output`

Examples:

```bash
kgnite download dataset zillow/zecon --output-dir ./downloads
kgnite download dataset zillow/zecon --path data.csv --output-dir ./downloads
kgnite download competition titanic --output-dir ./downloads
kgnite download model google/gemma/pytorch/2b/3 --output-dir ./models
kgnite download notebook-output kaggle/getting-started-with-ai4code --output-dir ./nb-output
```

### Pull notebook source

Notebook source and notebook output are different operations.

```bash
kgnite pull-notebook kaggle/getting-started-with-ai4code --output-dir ./notebooks
```

## 8. Competition Workflows

### Submit a file

```bash
kgnite submit titanic --file ./submission.csv --message "baseline v1"
```

### Submit a notebook version in a code competition

```bash
kgnite submit some-code-competition \
  --kernel yourname/your-notebook \
  --version 3 \
  --message "submit notebook version 3"
```

### View leaderboard

```bash
kgnite leaderboard titanic --show
kgnite leaderboard titanic --show --page-size 50
kgnite leaderboard titanic --download --output-dir ./leaderboards
```

### View your submissions

```bash
kgnite submissions titanic
kgnite submissions titanic --json
```

If Kaggle rejects submission-history access, `kgnite` now returns a clearer explanation instead of only a raw API error. Typical causes:

- you have not joined the competition yet
- you have not accepted the competition rules
- you have no submissions yet
- Kaggle API access for submissions is restricted for that competition/account state

## 9. Upload Workflows

### Upload a dataset

Handle-driven upload through `kagglehub`:

```bash
kgnite upload-dataset ./my-dataset \
  --handle yourname/my-dataset \
  --message "initial upload"
```

Kaggle CLI metadata-folder upload:

```bash
kgnite upload-dataset ./my-dataset --public
kgnite upload-dataset ./my-dataset --version --message "new rows for march"
```

Notes:

- handle mode is simpler if you already know the dataset target
- CLI mode expects Kaggle dataset metadata files in the folder

### Upload a model

Handle-driven upload through `kagglehub`:

```bash
kgnite upload-model ./my-model \
  --handle yourname/my-model/pytorch/base \
  --license-name Apache-2.0 \
  --message "initial model version"
```

Kaggle CLI metadata-folder mode:

```bash
kgnite upload-model ./my-model --action create
kgnite upload-model ./my-model --action update
```

Notes:

- `kagglehub` mode is best for direct artifact uploads
- CLI mode expects Kaggle model metadata files in the folder

## 10. Interactive Browse Mode

Run:

```bash
kgnite browse
```

What `browse` does:

1. Shows a resource menu
2. Accepts either:
   - a number: `1`, `2`, `3`, `4`
   - a resource name: `datasets`, `competitions`, `kernels`, `models`
   - or a direct search query like `llm` or `gemma`
3. Shows search results
4. Lets you pick a result number
5. Lets you choose an action

Resource menu:

```text
1. datasets
2. competitions
3. kernels
4. models
```

Examples:

```text
kgnite browse
1
titanic
1
info
```

```text
kgnite browse
datasets
titanic
1
download
```

```text
kgnite browse
llm
1
info
```

### Browse download destination behavior

When you choose a download action in `browse`, `kgnite` asks where to save the files.

Options:

1. Default cache folder
2. Current folder
3. Custom folder

Default base folders:

- datasets: `~/.cache/kagglehub/datasets`
- competitions: `~/.cache/kagglehub/competitions`
- kernels: `~/.cache/kagglehub/notebooks`
- models: `~/.cache/kagglehub/models`

`kgnite` then creates a resource-specific subfolder under the chosen base path, so downloads do not collide with existing files.

Examples:

- dataset:
  - `~/.cache/kagglehub/datasets/<owner>/<dataset>`
- competition:
  - `~/.cache/kagglehub/competitions/<competition>`
- kernel output:
  - `~/.cache/kagglehub/notebooks/<owner>/<notebook>`
- notebook source pull into current folder:
  - `./<owner>/<notebook>/...`

## 11. Maintenance

### Reinstall after code changes

If you changed the project code and want the installed tool updated:

```bash
cd /Users/rajeshsingh/myprojects/kgnite
bash scripts/install.sh
```

If you use `/usr/local/bin`, rerun the printed `sudo install ...` command only if needed.

### Check installed runtime

```bash
kgnite doctor
```

### Uninstall

```bash
cd /Users/rajeshsingh/myprojects/kgnite
bash scripts/uninstall.sh
```

If the launcher is in `/usr/local/bin` and cannot be removed without elevated privileges, the uninstall script tells you the `sudo rm ...` command to run.

### Makefile shortcuts

You can also use:

```bash
make install
make reinstall
make uninstall
make dev
make completions
```

## 12. Design Notes

- search, listings, metadata, and competition actions primarily wrap the Kaggle CLI
- downloads primarily use `kagglehub`
- notebook source pulls and notebook output downloads remain separate because Kaggle treats them as separate resources

## 13. Current Limits

- `browse` is interactive terminal guidance, not a full TUI
- `upload-model` CLI mode only wraps metadata-based model create/update flows
- model downloads are most reliable with full handles like `<owner>/<model>/<framework>/<variation>/<version>`
