# QUICKSTART

## 1. Configure Kaggle

Preferred auth:

```bash
export KAGGLE_API_TOKEN="your_token_here"
```

Verify:

```bash
kaggle config view
```

## 2. Install kgtool

System-style install:

```bash
cd /Users/rajeshsingh/myprojects/kgtool
bash scripts/install.sh
sudo install -m 755 "/Users/rajeshsingh/.local/share/kgtool/kgtool-launcher" "/usr/local/bin/kgtool"
hash -r
```

Then set up completions:

```bash
kgtool completions
```

User-local install without sudo:

```bash
cd /Users/rajeshsingh/myprojects/kgtool
KGTOOL_BIN_DIR="$HOME/.local/bin" bash scripts/install.sh
export PATH="$HOME/.local/bin:$PATH"
hash -r
```

Then set up completions:

```bash
kgtool completions
```

## 3. Verify

```bash
kgtool --help
kgtool doctor
kgtool usage
kgtool completions
```

## 4. Common commands

```bash
kgtool search datasets titanic
kgtool info dataset heptapod/titanic
kgtool files competition titanic
kgtool download dataset heptapod/titanic --output-dir ./downloads
kgtool leaderboard titanic --show
kgtool browse
```

## 5. Browse tips

- type `1`, `2`, `3`, `4` to choose a resource
- or type `datasets`, `competitions`, `kernels`, `models`
- or type a search query directly like `llm` or `gemma`
- download actions in `browse` ask where to save files before downloading

## 6. Maintenance

Reinstall after code changes:

```bash
cd /Users/rajeshsingh/myprojects/kgtool
bash scripts/install.sh
```

Uninstall:

```bash
cd /Users/rajeshsingh/myprojects/kgtool
bash scripts/uninstall.sh
```
