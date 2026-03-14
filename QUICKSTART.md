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

## 2. Install kgnite

System-style install:

```bash
cd /Users/rajeshsingh/myprojects/kgnite
bash scripts/install.sh
sudo install -m 755 "/Users/rajeshsingh/.local/share/kgnite/kgnite-launcher" "/usr/local/bin/kgnite"
hash -r
```

Then set up completions:

```bash
kgnite completions
```

User-local install without sudo:

```bash
cd /Users/rajeshsingh/myprojects/kgnite
KGNITE_BIN_DIR="$HOME/.local/bin" bash scripts/install.sh
export PATH="$HOME/.local/bin:$PATH"
hash -r
```

Then set up completions:

```bash
kgnite completions
```

## 3. Verify

```bash
kgnite --help
kgnite doctor
kgnite usage
kgnite completions
```

## 4. Common commands

```bash
kgnite search datasets titanic
kgnite info dataset heptapod/titanic
kgnite files competition titanic
kgnite download dataset heptapod/titanic --output-dir ./downloads
kgnite leaderboard titanic --show
kgnite browse
```

## 5. Browse tips

- type `1`, `2`, `3`, `4` to choose a resource
- or type `datasets`, `competitions`, `kernels`, `models`
- or type a search query directly like `llm` or `gemma`
- download actions in `browse` ask where to save files before downloading

## 6. Maintenance

Reinstall after code changes:

```bash
cd /Users/rajeshsingh/myprojects/kgnite
bash scripts/install.sh
```

Uninstall:

```bash
cd /Users/rajeshsingh/myprojects/kgnite
bash scripts/uninstall.sh
```
