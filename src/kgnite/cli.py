from __future__ import annotations

import argparse
import contextlib
import csv
import getpass
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:
    import kagglehub
    from kagglehub.config import get_kaggle_credentials
    from kagglehub.handle import (
        parse_competition_handle,
        parse_dataset_handle,
        parse_model_handle,
        parse_notebook_handle,
    )

    KAGGLEHUB_IMPORT_ERROR: Exception | None = None
except (ImportError, ModuleNotFoundError) as exc:
    kagglehub = None  # type: ignore[assignment]
    get_kaggle_credentials = None  # type: ignore[assignment]
    parse_competition_handle = None  # type: ignore[assignment]
    parse_dataset_handle = None  # type: ignore[assignment]
    parse_model_handle = None  # type: ignore[assignment]
    parse_notebook_handle = None  # type: ignore[assignment]
    KAGGLEHUB_IMPORT_ERROR = exc

from kgnite.features import (
    choose_preview_file,
    create_competition_workspace,
    create_project_workspace,
    filter_resource_rows,
    load_score_history,
    merge_score_history,
    next_competition_notebook_path,
    kaggle_notebook_slug,
    normalize_scores,
    notebook_title_from_slug,
    preview_local_file,
    prepare_kaggle_notebook_bundle,
    prepare_local_dataset_bundle,
    save_score_history,
    score_sparkline,
    write_starter_notebook,
    write_workspace_help,
)
from kgnite.settings import load_settings, save_settings, workspace_subdir

APP_NAME = "kgnite"
USAGE_TEXT = """\
Common workflows:
  kgnite doctor
  kgnite completions
  kgnite search datasets "vision transformer" --sort-by votes
  kgnite info dataset zillow/zecon
  kgnite files competition titanic
  kgnite download dataset zillow/zecon --output-dir ./downloads
  kgnite preview dataset zillow/zecon --rows 10
  kgnite pull-notebook owner/notebook --output-dir ./notebooks
  kgnite prepare-notebook ./titanic/notebooks/titanic-01.ipynb --title "Titanic Random Forest" --competition titanic --public
  kgnite push-notebook ./titanic/kaggle-notebooks/titanic-random-forest
  kgnite submit titanic --file ./submission.csv --message "baseline"
  kgnite leaderboard titanic --show
  kgnite setup titanic --directory ./titanic
  kgnite template titanic --output ./titanic/notebooks/titanic-02.ipynb
  kgnite performance titanic --sync
  kgnite trending datasets --tag tabular
  kgnite web
  kgnite upload-dataset ./my-dataset --handle me/my-dataset --message "v1"
  kgnite upload-model ./my-model --handle me/model/pytorch/base --message "v1"
  kgnite browse
"""
COMMAND_HINTS = {
    "kgnite": [
        "kgnite usage",
        "kgnite completions",
        'kgnite search datasets "titanic"',
        "kgnite browse",
    ],
    "kgnite leaderboard": [
        "kgnite leaderboard titanic --show",
        "kgnite leaderboard titanic --download --output-dir ./leaderboards",
    ],
    "kgnite submissions": [
        "kgnite submissions titanic",
        "kgnite submissions titanic --json",
    ],
    "kgnite upload-dataset": [
        'kgnite upload-dataset ./my-dataset --handle yourname/my-dataset --message "v1"',
        'kgnite upload-dataset ./my-dataset --version --message "march refresh"',
    ],
    "kgnite upload-model": [
        'kgnite upload-model ./my-model --handle yourname/my-model/pytorch/base --message "v1"',
        "kgnite upload-model ./my-model --action create",
    ],
    "kgnite browse": [
        "kgnite browse",
        "kgnite browse --resource datasets --search titanic",
        "kgnite browse --resource kernels --search rag --output-dir ./tmp",
    ],
    "kgnite completions": [
        "kgnite completions",
        "kgnite completions --shell zsh",
        "kgnite completions --print",
    ],
    "kgnite web": [
        "kgnite web",
        "kgnite web --port 8765",
        "kgnite web --no-browser",
    ],
}


class KgniteError(RuntimeError):
    pass


def require_kagglehub() -> Any:
    if kagglehub is None:
        raise KgniteError(
            "kagglehub could not be imported. Reinstall kgnite dependencies. "
            f"Upstream import error: {KAGGLEHUB_IMPORT_ERROR}"
        )
    return kagglehub


class KgniteArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stdout)
        print(f"{self.prog}: error: {message}")
        hints = COMMAND_HINTS.get(self.prog)
        if hints:
            print()
            print("Examples:")
            for hint in hints:
                print(f"  {hint}")
        if self.prog == APP_NAME:
            print()
            print_usage_guide()
        raise SystemExit(2)


def run_kaggle(
    args: list[str], *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    command = ["kaggle", *args]
    try:
        return subprocess.run(
            command,
            check=check,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise KgniteError("The `kaggle` CLI is not installed or not on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        message = stderr or stdout or f"`{' '.join(command)}` failed"
        raise KgniteError(message) from exc


def parse_csv_output(text: str) -> list[dict[str, str]]:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return []
    start_index = 0
    for index, line in enumerate(lines):
        if "," in line and not line.lower().startswith("next page token"):
            start_index = index
            break
    csv_lines = lines[start_index:]
    reader = csv.DictReader(csv_lines)
    if reader.fieldnames is None:
        return []
    return list(reader)


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No results.")
        return

    headers = list(rows[0].keys())
    widths: dict[str, int] = {header: len(header) for header in headers}
    str_rows: list[dict[str, str]] = []
    for row in rows:
        string_row = {
            header: "" if row.get(header) is None else str(row.get(header))
            for header in headers
        }
        str_rows.append(string_row)
        for header, value in string_row.items():
            widths[header] = max(widths[header], len(value))

    print("  ".join(header.ljust(widths[header]) for header in headers))
    print("  ".join("-" * widths[header] for header in headers))
    for row in str_rows:
        print("  ".join(row[header].ljust(widths[header]) for header in headers))


def print_usage_guide() -> None:
    print(textwrap.dedent(USAGE_TEXT).strip())


def prompt(text: str, *, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    try:
        print(f"{text}{suffix}: ", end="", flush=True)
        value = input().strip()
    except EOFError:
        return ""
    if value:
        return value
    if default is not None:
        return default
    return ""


def choose_resource(default: str = "datasets") -> str:
    options = {
        "1": "datasets",
        "2": "competitions",
        "3": "kernels",
        "4": "models",
    }
    print("Choose a resource:")
    print("  1. datasets")
    print("  2. competitions")
    print("  3. kernels")
    print("  4. models")
    print("You can also type a search query directly to use the default resource.")
    print()
    choice = prompt("Enter number or search query", default="1")
    selected = options.get(choice)
    if selected:
        return selected
    normalized = try_normalize_resource(choice)
    if normalized:
        return normalized
    return default


def default_download_dir(resource: str) -> str:
    cache_root = Path.home() / ".cache" / "kagglehub"
    mapping = {
        "datasets": cache_root / "datasets",
        "competitions": cache_root / "competitions",
        "models": cache_root / "models",
        "kernels": cache_root / "notebooks",
    }
    return str(mapping[resource])


def choose_download_destination(resource: str) -> str:
    default_dir = default_download_dir(resource)
    current_dir = str(Path.cwd())

    print("Choose download destination:")
    print(f"  1. Default cache folder [{default_dir}]")
    print(f"  2. Current folder [{current_dir}]")
    print("  3. Custom folder")
    print()

    choice = prompt("Enter 1, 2, or 3", default="1")
    if choice == "1":
        return default_dir
    if choice == "2":
        return current_dir
    if choice == "3":
        custom_dir = prompt("Custom folder path")
        if not custom_dir:
            print(
                f"No custom folder entered. Using default cache folder: {default_dir}"
            )
            return default_dir
        return str(Path(custom_dir).expanduser().resolve())

    normalized = try_normalize_resource(choice)
    if normalized:
        print(
            f"Input `{choice}` looks like a resource, not a folder choice. Using default cache folder: {default_dir}"
        )
        return default_dir

    return str(Path(choice).expanduser().resolve())


def download_target_dir(resource: str, handle: str, base_dir: str) -> str:
    base = Path(base_dir).expanduser().resolve()
    if resource == "competitions":
        return str(base / handle)
    return str(base.joinpath(*handle.split("/")))


def detect_shell() -> str:
    shell = os.environ.get("SHELL", "")
    name = Path(shell).name.lower()
    if "zsh" in name:
        return "zsh"
    if "bash" in name:
        return "bash"
    return "zsh"


def completions_dir() -> Path:
    return Path.home() / ".local" / "share" / "kgnite" / "completions"


def bash_completion_script() -> str:
    return textwrap.dedent(
        """\
        _kgnite_completions() {
          local cur prev words cword
          _init_completion || return

          local commands="usage doctor completions settings create-project workspace-help search setup template performance trending web info files download preview pull-notebook prepare-notebook push-notebook submit leaderboard submissions upload-dataset upload-model browse"
          local resources_plural="datasets competitions kernels models"
          local resources_singular="dataset competition notebook model"
          local download_resources="dataset competition model notebook-output"
          local model_actions="create update"

          if [[ $cword -eq 1 ]]; then
            COMPREPLY=( $(compgen -W "$commands" -- "$cur") )
            return
          fi

          case "${words[1]}" in
            completions)
              COMPREPLY=( $(compgen -W "--shell --print" -- "$cur") )
              ;;
            settings)
              COMPREPLY=( $(compgen -W "--workspace-dir --competitions-dir --projects-dir --kaggle-username --default-dataset-license --json" -- "$cur") )
              ;;
            create-project)
              COMPREPLY=( $(compgen -W "--directory --participant --dataset-source --kernel-source --model-source --template --no-template --force --json" -- "$cur") )
              ;;
            workspace-help)
              if [[ "$prev" == "--type" ]]; then
                COMPREPLY=( $(compgen -W "competition project" -- "$cur") )
                return
              fi
              COMPREPLY=( $(compgen -W "--type --directory --json" -- "$cur") )
              ;;
            search)
              if [[ $cword -eq 2 ]]; then
                COMPREPLY=( $(compgen -W "$resources_plural" -- "$cur") )
                return
              fi
              COMPREPLY=( $(compgen -W "--sort-by --page --page-size --owner --user --category --group --language --kernel-type --output-type --dataset --competition --tag --keyword --json" -- "$cur") )
              ;;
            setup)
              COMPREPLY=( $(compgen -W "--directory --metric --participant --competition-notes --no-competition-notes --notes-page --lower-is-better --no-lower-is-better --download --no-download --template --no-template --force --json" -- "$cur") )
              ;;
            template)
              COMPREPLY=( $(compgen -W "--output --data-dir --participant --competition-notes --no-competition-notes --notes-page --force --json" -- "$cur") )
              ;;
            performance)
              COMPREPLY=( $(compgen -W "--sync --history --lower-is-better --json" -- "$cur") )
              ;;
            trending)
              COMPREPLY=( $(compgen -W "datasets competitions kernels models --order --search --tag --keyword --category --limit --json" -- "$cur") )
              ;;
            web)
              COMPREPLY=( $(compgen -W "--port --browser --no-browser --heartbeat-timeout --command-timeout" -- "$cur") )
              ;;
            info)
              if [[ $cword -eq 2 ]]; then
                COMPREPLY=( $(compgen -W "$resources_singular" -- "$cur") )
                return
              fi
              COMPREPLY=( $(compgen -W "--json" -- "$cur") )
              ;;
            files)
              if [[ $cword -eq 2 ]]; then
                COMPREPLY=( $(compgen -W "$resources_singular" -- "$cur") )
                return
              fi
              COMPREPLY=( $(compgen -W "--page-size --page-token --json" -- "$cur") )
              ;;
            download)
              if [[ $cword -eq 2 ]]; then
                COMPREPLY=( $(compgen -W "$download_resources" -- "$cur") )
                return
              fi
              COMPREPLY=( $(compgen -W "--path --output-dir --force --json" -- "$cur") )
              ;;
            preview)
              COMPREPLY=( $(compgen -W "dataset local url --path --rows --columns --max-file-size-mb --force --json" -- "$cur") )
              ;;
            pull-notebook)
              COMPREPLY=( $(compgen -W "--output-dir --json" -- "$cur") )
              ;;
            prepare-notebook)
              COMPREPLY=( $(compgen -W "--handle --competition --dataset-source --competition-source --kernel-source --model-source --local-dataset --dataset-handle --dataset-title --dataset-license --title --output-dir --public --enable-internet --enable-gpu --force --json" -- "$cur") )
              ;;
            push-notebook)
              if [[ "$prev" == "--dataset-action" ]]; then
                COMPREPLY=( $(compgen -W "create version" -- "$cur") )
                return
              fi
              COMPREPLY=( $(compgen -W "--timeout --accelerator --with-datasets --dataset-action --public-datasets --no-public-datasets --json" -- "$cur") )
              ;;
            submit)
              COMPREPLY=( $(compgen -W "--file --kernel --version --message --json" -- "$cur") )
              ;;
            leaderboard)
              COMPREPLY=( $(compgen -W "--show --download --output-dir --page-size --page-token --json" -- "$cur") )
              ;;
            submissions)
              COMPREPLY=( $(compgen -W "--json" -- "$cur") )
              ;;
            upload-dataset)
              COMPREPLY=( $(compgen -W "--handle --message --ignore --version --public --keep-tabular --dir-mode --delete-old-versions --json" -- "$cur") )
              ;;
            upload-model)
              if [[ "$prev" == "--action" ]]; then
                COMPREPLY=( $(compgen -W "$model_actions" -- "$cur") )
                return
              fi
              COMPREPLY=( $(compgen -W "--handle --message --license-name --ignore --sigstore --action --json" -- "$cur") )
              ;;
            browse)
              if [[ "$prev" == "--resource" ]]; then
                COMPREPLY=( $(compgen -W "$resources_plural" -- "$cur") )
                return
              fi
              COMPREPLY=( $(compgen -W "--resource --search --sort-by --page --page-size --limit --output-dir" -- "$cur") )
              ;;
          esac
        }

        complete -F _kgnite_completions kgnite
        """
    )


def zsh_completion_script() -> str:
    return textwrap.dedent(
        """\
        #compdef kgnite

        local -a commands
        commands=(
          'usage:Show example workflows'
          'doctor:Inspect auth and runtime state'
          'completions:Install or print shell completions'
          'settings:Show or update persistent settings'
          'create-project:Create a generic Kaggle-ready project'
          'workspace-help:Create or refresh a workspace guide'
          'search:Search Kaggle resources'
          'setup:Create a competition workspace'
          'template:Generate a starter notebook'
          'performance:Track submission scores'
          'trending:Show popular or new resources'
          'web:Launch the local browser app'
          'info:Show resource metadata'
          'files:List resource files'
          'download:Download Kaggle assets'
          'preview:Preview rows from a dataset file'
          'pull-notebook:Pull notebook source'
          'prepare-notebook:Prepare a Kaggle Notebook upload bundle'
          'push-notebook:Create or update a prepared Kaggle Notebook'
          'submit:Submit competition result'
          'leaderboard:Show or download competition leaderboard'
          'submissions:List competition submissions'
          'upload-dataset:Upload or version a dataset'
          'upload-model:Upload or update a model'
          'browse:Interactive browse workflow'
        )

        local -a plural_resources singular_resources download_resources
        plural_resources=(datasets competitions kernels models)
        singular_resources=(dataset competition notebook model)
        download_resources=(dataset competition model notebook-output)

        case $CURRENT in
          2)
            _describe 'command' commands
            return
            ;;
        esac

        case "${words[2]}" in
          completions)
            _arguments '--shell[Shell]:shell:(bash zsh)' '--print[Print script]'
            ;;
          settings)
            _arguments '--workspace-dir[Workspace root]:folder:_files -/' '--competitions-dir[Competitions folder]:folder:' '--projects-dir[Projects folder]:folder:' '--kaggle-username[Kaggle username]:username:' '--default-dataset-license[Default dataset license]:license:' '--json[Print JSON]'
            ;;
          create-project)
            _arguments '--directory[Project directory]:folder:_files -/' '--participant[Participant name]:name:' '*--dataset-source[Kaggle dataset source]:handle:' '*--kernel-source[Kaggle notebook source]:handle:' '*--model-source[Kaggle model source]:handle:' '--template[Generate starter notebook]' '--no-template[Skip starter notebook]' '--force[Replace generated files]' '--json[Print JSON]'
            ;;
          workspace-help)
            _arguments '--type[Workspace type]:type:(competition project)' '--directory[Workspace directory]:folder:_files -/' '--json[Print JSON]'
            ;;
          search)
            if (( CURRENT == 3 )); then
              _values 'resource' $plural_resources
              return
            fi
            _arguments '--sort-by[Sort order]' '--page[Page number]:page:' '--page-size[Page size]:page size:' '--owner[Owner]:owner:' '--user[User]:user:' '--category[Competition category]:category:(all featured research recruitment gettingStarted masters playground)' '--group[Competition group]:group:(general entered inClass)' '--language[Kernel language]:language:(all python r sqlite julia)' '--kernel-type[Kernel type]:type:(all script notebook)' '--output-type[Kernel output type]:type:(all visualizations data)' '--dataset[Dataset filter]:dataset:' '--competition[Competition filter]:competition:' '*--tag[Required tag]:tag:' '*--keyword[Required keyword]:keyword:' '--json[Print JSON]'
            ;;
          setup)
            _arguments '--directory[Workspace]:folder:_files -/' '--metric[Metric]:metric:' '--participant[Participant name]:name:' '--competition-notes' '--no-competition-notes' '*--notes-page[Competition notes page]:page:' '--lower-is-better' '--no-lower-is-better' '--download' '--no-download' '--template' '--no-template' '--force' '--json'
            ;;
          template)
            _arguments '--output[Notebook]:file:_files' '--data-dir[Data directory]:folder:_files -/' '--participant[Participant name]:name:' '--competition-notes' '--no-competition-notes' '*--notes-page[Competition notes page]:page:' '--force' '--json'
            ;;
          performance)
            _arguments '--sync' '--history[History file]:file:_files' '--lower-is-better' '--json'
            ;;
          trending)
            _arguments '--order[Order]:order:(popular new)' '--search[Query]:query:' '*--tag[Required tag]:tag:' '*--keyword[Required keyword]:keyword:' '--category[Category]:category:' '--limit[Limit]:limit:' '--json'
            ;;
          web)
            _arguments '--port[Local port]:port:' '--browser[Open browser]' '--no-browser[Print URL only]' '--heartbeat-timeout[Page heartbeat timeout]:seconds:' '--command-timeout[Command timeout]:seconds:'
            ;;
          info)
            if (( CURRENT == 3 )); then
              _values 'resource' $singular_resources
              return
            fi
            _arguments '--json[Print JSON]'
            ;;
          files)
            if (( CURRENT == 3 )); then
              _values 'resource' $singular_resources
              return
            fi
            _arguments '--page-size[Page size]:page size:' '--page-token[Page token]:token:' '--json[Print JSON]'
            ;;
          download)
            if (( CURRENT == 3 )); then
              _values 'resource' $download_resources
              return
            fi
            _arguments '--path[Remote path]:path:' '--output-dir[Destination]:folder:_files -/' '--force[Force fresh download]' '--json[Print JSON]'
            ;;
          preview)
            _arguments '--path[Remote file]:path:' '--rows[Row limit]:rows:' '--columns[Column limit]:columns:' '--max-file-size-mb[Maximum file size]:megabytes:' '--force[Refresh cached file]' '--json[Print JSON]'
            ;;
          pull-notebook)
            _arguments '--output-dir[Destination]:folder:_files -/' '--json[Print JSON]'
            ;;
          prepare-notebook)
            _arguments '--handle[Kaggle notebook owner/slug]:handle:' '--competition[Linked competition slug]:competition:' '*--dataset-source[Kaggle dataset source]:handle:' '*--competition-source[Kaggle competition source]:slug:' '*--kernel-source[Kaggle notebook source]:handle:' '*--model-source[Kaggle model source]:handle:' '--local-dataset[Local dataset directory]:folder:_files -/' '--dataset-handle[Kaggle dataset handle]:handle:' '--dataset-title[Dataset title]:title:' '--dataset-license[Dataset license]:license:' '--title[Notebook title]:title:' '--output-dir[Bundle destination]:folder:_files -/' '--public[Prepare public notebook]' '--enable-internet[Enable internet]' '--enable-gpu[Enable GPU]' '--force[Replace prepared bundle]' '--json[Print JSON]'
            ;;
          push-notebook)
            _arguments '--timeout[Timeout seconds]:seconds:' '--accelerator[Accelerator]:accelerator:' '--with-datasets[Push staged local datasets first]' '--dataset-action[Dataset action]:action:(create version)' '--public-datasets[Create staged datasets as public]' '--no-public-datasets[Create staged datasets as private]' '--json[Print JSON]'
            ;;
          submit)
            _arguments '--file[Submission file]:file:_files' '--kernel[Notebook handle]:kernel:' '--version[Notebook version]:version:' '--message[Submission message]:message:' '--json[Print JSON]'
            ;;
          leaderboard)
            _arguments '--show[Show leaderboard]' '--download[Download leaderboard]' '--output-dir[Destination]:folder:_files -/' '--page-size[Page size]:page size:' '--page-token[Page token]:token:' '--json[Print JSON]'
            ;;
          submissions)
            _arguments '--json[Print JSON]'
            ;;
          upload-dataset)
            _arguments '--handle[Dataset handle]:handle:' '--message[Version notes]:message:' '--ignore[Ignore patterns]:pattern:' '--version[Use version mode]' '--public[Create public dataset]' '--keep-tabular[Keep tabular files]' '--dir-mode[Directory mode]:mode:(skip zip tar)' '--delete-old-versions[Delete old versions]' '--json[Print JSON]'
            ;;
          upload-model)
            _arguments '--handle[Model handle]:handle:' '--message[Version notes]:message:' '--license-name[License]:license:' '--ignore[Ignore patterns]:pattern:' '--sigstore[Enable sigstore]' '--action[CLI action]:action:(create update)' '--json[Print JSON]'
            ;;
          browse)
            _arguments '--resource[Default resource]:resource:((datasets datasets competitions competitions kernels kernels models models))' '--search[Default search query]:query:' '--sort-by[Sort order]:sort:' '--page[Page number]:page:' '--page-size[Page size]:page size:' '--limit[Result limit]:limit:' '--output-dir[Destination folder]:folder:_files -/'
            ;;
        esac
        """
    )


def shell_completion_script(shell: str) -> str:
    if shell == "bash":
        return bash_completion_script()
    if shell == "zsh":
        return zsh_completion_script()
    raise KgniteError(f"Unsupported shell for completions: {shell}")


def normalize_resource(resource: str) -> str:
    mapping = {
        "dataset": "datasets",
        "datasets": "datasets",
        "competition": "competitions",
        "competitions": "competitions",
        "notebook": "kernels",
        "notebooks": "kernels",
        "kernel": "kernels",
        "kernels": "kernels",
        "model": "models",
        "models": "models",
    }
    normalized = mapping.get(resource.lower())
    if not normalized:
        raise KgniteError(f"Unsupported resource: {resource}")
    return normalized


def try_normalize_resource(resource: str | None) -> str | None:
    if not resource:
        return None
    mapping = {
        "dataset": "datasets",
        "datasets": "datasets",
        "competition": "competitions",
        "competitions": "competitions",
        "notebook": "kernels",
        "notebooks": "kernels",
        "kernel": "kernels",
        "kernels": "kernels",
        "model": "models",
        "models": "models",
    }
    return mapping.get(resource.lower())


def validate_resource_handle(resource: str, handle: str) -> None:
    normalized = normalize_resource(resource)
    parts = [part for part in handle.strip().split("/") if part]
    if normalized == "datasets" and len(parts) < 2:
        raise KgniteError(
            "Dataset handle must be `owner/dataset-slug`, not a search query. "
            f"Run `kgnite search datasets {handle}` and use a result's `ref` value."
        )
    if normalized == "kernels" and len(parts) < 2:
        raise KgniteError(
            "Notebook handle must be `owner/notebook-slug`. "
            f"Run `kgnite search kernels {handle}` and use a result's `ref` value."
        )
    if normalized == "models" and len(parts) < 2:
        raise KgniteError(
            "Model handle must begin with `owner/model`. "
            f"Run `kgnite search models {handle}` and use a result's `ref` value."
        )


def handle_url(resource: str, handle: str) -> str:
    require_kagglehub()
    assert parse_dataset_handle is not None
    assert parse_competition_handle is not None
    assert parse_notebook_handle is not None
    assert parse_model_handle is not None
    if resource == "datasets":
        parsed = parse_dataset_handle(handle)
        url = f"https://www.kaggle.com/datasets/{parsed.owner}/{parsed.dataset}"
        if parsed.version:
            return f"{url}/versions/{parsed.version}"
        return url
    if resource == "competitions":
        parsed = parse_competition_handle(handle)
        return f"https://www.kaggle.com/competitions/{parsed.competition}"
    if resource == "kernels":
        parsed = parse_notebook_handle(handle)
        url = f"https://www.kaggle.com/code/{parsed.owner}/{parsed.notebook}"
        if parsed.version:
            return f"{url}/versions/{parsed.version}"
        return url
    if resource == "models":
        parts = handle.split("/")
        if len(parts) == 2:
            return f"https://www.kaggle.com/models/{handle}"
        if len(parts) >= 4:
            parsed = parse_model_handle(handle)
            url = f"https://www.kaggle.com/models/{parsed.owner}/{parsed.model}/{parsed.framework}/{parsed.variation}"
            if parsed.version:
                return f"{url}/{parsed.version}"
            return url
        return f"https://www.kaggle.com/models/{handle}"
    raise KgniteError(f"Unsupported resource: {resource}")


def auth_summary() -> dict[str, Any]:
    config_dir = Path(os.environ.get("KAGGLE_CONFIG_DIR", Path.home() / ".kaggle"))
    kaggle_json = config_dir / "kaggle.json"
    credentials = get_kaggle_credentials() if get_kaggle_credentials else None
    api_token = os.environ.get("KAGGLE_API_TOKEN")
    kaggle_key = os.environ.get("KAGGLE_KEY")
    kaggle_username = os.environ.get("KAGGLE_USERNAME")

    auth_method = None
    config_view_error = None
    try:
        config_view = (
            run_kaggle(["config", "view"], check=True).stdout.strip().splitlines()
        )
        for line in config_view:
            stripped = line.strip()
            if stripped.startswith("- auth_method:"):
                auth_method = stripped.split(":", 1)[1].strip()
    except KgniteError as exc:
        config_view_error = str(exc)

    return {
        "kaggle_cli_on_path": shutil.which("kaggle") is not None,
        "kagglehub_version": getattr(kagglehub, "__version__", "unavailable"),
        "kagglehub_import_error": (
            str(KAGGLEHUB_IMPORT_ERROR) if KAGGLEHUB_IMPORT_ERROR else None
        ),
        "kaggle_api_token_env": bool(api_token),
        "legacy_env_credentials": bool(kaggle_key and kaggle_username),
        "kaggle_json_exists": kaggle_json.exists(),
        "kaggle_json_path": str(kaggle_json),
        "kagglehub_credentials_detected": credentials is not None,
        "detected_auth_mode": (
            "access_token"
            if credentials and getattr(credentials, "api_key", None)
            else "username_key"
            if credentials
            and getattr(credentials, "username", None)
            and getattr(credentials, "key", None)
            else "missing"
        ),
        "kaggle_cli_auth_method": auth_method,
        "config_view_error": config_view_error,
    }


def search_rows(args: argparse.Namespace) -> list[dict[str, str]]:
    resource = normalize_resource(args.resource)
    command = [resource, "list", "--csv"]

    if args.search:
        command += ["--search", args.search]
    if getattr(args, "sort_by", None):
        command += ["--sort-by", args.sort_by]
    if getattr(args, "page", None) is not None and resource in {
        "datasets",
        "competitions",
        "kernels",
    }:
        command += ["--page", str(args.page)]
    if getattr(args, "page_size", None) is not None and resource in {
        "competitions",
        "kernels",
        "models",
    }:
        command += ["--page-size", str(args.page_size)]
    if getattr(args, "owner", None) and resource == "models":
        command += ["--owner", args.owner]
    if getattr(args, "user", None) and resource in {"datasets", "kernels"}:
        command += ["--user", args.user]
    if getattr(args, "category", None) and resource == "competitions":
        command += ["--category", args.category]
    if getattr(args, "group", None) and resource == "competitions":
        command += ["--group", args.group]
    if getattr(args, "language", None) and resource == "kernels":
        command += ["--language", args.language]
    if getattr(args, "kernel_type", None) and resource == "kernels":
        command += ["--kernel-type", args.kernel_type]
    if getattr(args, "output_type", None) and resource == "kernels":
        command += ["--output-type", args.output_type]
    if getattr(args, "dataset", None) and resource == "kernels":
        command += ["--dataset", args.dataset]
    if getattr(args, "competition", None) and resource == "kernels":
        command += ["--competition", args.competition]

    result = run_kaggle(command)
    return filter_resource_rows(
        parse_csv_output(result.stdout),
        tags=getattr(args, "tag", None) or (),
        keywords=getattr(args, "keyword", None) or (),
    )


def add_common_output_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json", action="store_true", help="Print JSON instead of a table."
    )


def command_doctor(args: argparse.Namespace) -> int:
    summary = auth_summary()
    if args.json:
        print_json(summary)
        return 0

    rows = [{"check": key, "value": value} for key, value in summary.items()]
    print_table(rows)
    print()
    if summary["detected_auth_mode"] == "access_token":
        print(
            "Recommendation: keep using KAGGLE_API_TOKEN. It is already detected by kagglehub."
        )
    elif summary["detected_auth_mode"] == "username_key":
        print("Recommendation: current setup uses legacy username/key credentials.")
    else:
        print(
            "Recommendation: no Kaggle credentials detected. Configure them before downloading."
        )
    return 0


def command_search(args: argparse.Namespace) -> int:
    rows = search_rows(args)
    if args.json:
        print_json(rows)
    else:
        print_table(rows)
    return 0


def fetch_competition_notes(competition: str, pages: list[str]) -> list[dict[str, str]]:
    notes: list[dict[str, str]] = []
    for page in pages:
        result = run_kaggle(
            [
                "competitions",
                "pages",
                competition,
                "--content",
                "--page-name",
                page,
                "--format",
                "json",
            ]
        )
        try:
            entries = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise KgniteError(
                f"Kaggle returned invalid notes content for page `{page}`."
            ) from exc
        if not entries:
            raise KgniteError(f"Competition page was not found: {page}")
        entry = entries[0]
        page_name = str(entry.get("name") or page)
        if page_name.casefold() == "data-description":
            url = f"https://www.kaggle.com/competitions/{competition}/data"
        elif page_name.casefold() == "rules":
            url = f"https://www.kaggle.com/competitions/{competition}/rules"
        else:
            url = f"https://www.kaggle.com/competitions/{competition}/overview/{page_name.casefold()}"
        notes.append(
            {"name": page_name, "content": str(entry.get("content") or ""), "url": url}
        )
    return notes


def command_setup(args: argparse.Namespace) -> int:
    competition = args.competition or prompt("Competition slug")
    if not competition:
        raise KgniteError("A competition slug is required.")
    directory = Path(args.directory) if args.directory else workspace_subdir("competition", competition)
    metric = args.metric or (
        "publicScore" if args.json else prompt("Score metric", default="publicScore")
    )
    participant = (
        args.participant or os.environ.get("KGNITE_PARTICIPANT") or getpass.getuser()
    )
    lower_is_better = args.lower_is_better
    if lower_is_better is None:
        lower_is_better = (
            False
            if args.json
            else prompt("Is a lower score better? (y/N)", default="n")
            .lower()
            .startswith("y")
        )
    try:
        payload = create_competition_workspace(
            competition,
            directory,
            metric=metric,
            lower_is_better=lower_is_better,
            participant=participant,
            force=args.force,
        )
    except FileExistsError as exc:
        raise KgniteError(str(exc)) from exc

    should_download = args.download
    if should_download is None:
        should_download = (
            False
            if args.json
            else prompt("Download competition files now? (y/N)", default="n")
            .lower()
            .startswith("y")
        )
    if should_download:
        payload["downloaded_to"] = require_kagglehub().competition_download(
            competition,
            force_download=args.force,
            output_dir=str(directory.expanduser().resolve() / "data"),
        )

    should_template = args.template
    if should_template is None:
        should_template = (
            True
            if args.json
            else prompt("Generate a starter notebook? (Y/n)", default="y").lower()
            != "n"
        )
    if should_template:
        notes = (
            fetch_competition_notes(
                competition, args.notes_page or ["data-description"]
            )
            if args.competition_notes
            else []
        )
        try:
            notebook = write_starter_notebook(
                competition,
                directory / "notebooks" / f"{competition}-01.ipynb",
                directory / "data",
                participant=participant,
                competition_notes=notes,
                force=args.force,
            )
        except FileExistsError as exc:
            raise KgniteError(str(exc)) from exc
        payload["notebook"] = str(notebook)

    if args.json:
        print_json(payload)
    else:
        print(f"Competition workspace created: {payload['directory']}")
        if payload.get("downloaded_to"):
            print(f"Data downloaded to: {payload['downloaded_to']}")
        if payload.get("notebook"):
            print(f"Starter notebook: {payload['notebook']}")
    return 0


def command_template(args: argparse.Namespace) -> int:
    output = (
        Path(args.output)
        if args.output
        else next_competition_notebook_path(Path.cwd(), args.competition)
    )
    participant = (
        args.participant or os.environ.get("KGNITE_PARTICIPANT") or getpass.getuser()
    )
    notes = (
        fetch_competition_notes(
            args.competition, args.notes_page or ["data-description"]
        )
        if args.competition_notes
        else []
    )
    try:
        written = write_starter_notebook(
            args.competition,
            output,
            Path(args.data_dir),
            participant=participant,
            competition_notes=notes,
            force=args.force,
        )
    except FileExistsError as exc:
        raise KgniteError(str(exc)) from exc
    payload = {
        "competition": args.competition,
        "participant": participant,
        "notes_pages": [note["name"] for note in notes],
        "notebook": str(written),
        "data_dir": args.data_dir,
    }
    if args.json:
        print_json(payload)
    else:
        print(f"Starter notebook created: {written}")
    return 0


def command_performance(args: argparse.Namespace) -> int:
    history_path = (
        Path(args.history or Path(".kgnite") / f"{args.competition}-scores.json")
        .expanduser()
        .resolve()
    )
    try:
        history = load_score_history(history_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise KgniteError(f"Could not read score history: {exc}") from exc
    if args.sync:
        result = run_kaggle(["competitions", "submissions", args.competition, "--csv"])
        history = merge_score_history(
            history, normalize_scores(parse_csv_output(result.stdout), args.competition)
        )
        save_score_history(history_path, history)

    rows = [row for row in history if row.get("competition") == args.competition]
    scores = [float(row["score"]) for row in rows]
    best = (min(scores) if args.lower_is_better else max(scores)) if scores else None
    payload = {
        "competition": args.competition,
        "history": str(history_path),
        "submissions": len(rows),
        "best_score": best,
        "trend": score_sparkline(scores),
        "scores": rows,
    }
    if args.json:
        print_json(payload)
    else:
        print(f"Competition: {args.competition}")
        print(f"Submissions: {len(rows)}")
        print(f"Best score: {best if best is not None else 'n/a'}")
        print(f"Trend: {payload['trend'] or 'n/a'}")
        print_table(rows)
    return 0


def command_trending(args: argparse.Namespace) -> int:
    if args.limit < 1:
        raise KgniteError("--limit must be at least 1.")
    sort_orders = {
        "datasets": {"popular": "hottest", "new": "updated"},
        "competitions": {"popular": "numberOfTeams", "new": "recentlyCreated"},
        "kernels": {"popular": "hotness", "new": "dateCreated"},
        "models": {"popular": "hotness", "new": "createTime"},
    }
    search_args = argparse.Namespace(
        resource=args.resource,
        search=args.search,
        sort_by=sort_orders[args.resource][args.order],
        page=1,
        page_size=max(args.limit, 20),
        owner=None,
        user=None,
        category=args.category,
        group=None,
        language=None,
        kernel_type=None,
        output_type=None,
        dataset=None,
        competition=None,
        tag=args.tag,
        keyword=args.keyword,
    )
    rows = search_rows(search_args)[: args.limit]
    if args.json:
        print_json(rows)
    else:
        print_table(rows)
    return 0


def command_web(args: argparse.Namespace) -> int:
    from kgnite.webapp import serve_web_app

    try:
        return serve_web_app(
            port=args.port,
            open_browser=args.browser,
            heartbeat_timeout=args.heartbeat_timeout,
            command_timeout=args.command_timeout,
        )
    except (OSError, ValueError) as exc:
        raise KgniteError(f"Could not start the web app: {exc}") from exc


def list_files(
    resource: str,
    handle: str,
    *,
    page_size: int | None = None,
    page_token: str | None = None,
) -> list[dict[str, str]]:
    if resource == "datasets":
        command = ["datasets", "files", handle, "--csv"]
    elif resource == "competitions":
        command = ["competitions", "files", handle, "--csv"]
    elif resource == "kernels":
        command = ["kernels", "files", handle, "--csv"]
    elif resource == "models":
        command = ["models", "instances", "versions", "files", handle, "--csv"]
    else:
        raise KgniteError(f"Files listing is not supported for {resource}")

    if page_size is not None and resource in {"competitions", "models"}:
        command += ["--page-size", str(page_size)]
    if page_token and resource in {"competitions", "models"}:
        command += ["--page-token", page_token]

    return parse_csv_output(run_kaggle(command).stdout)


def load_json_file(directory: Path, pattern: str) -> dict[str, Any]:
    matches = list(directory.glob(pattern))
    if not matches:
        raise KgniteError(f"Expected metadata file matching {pattern} was not created.")
    with matches[0].open() as fh:
        return json.load(fh)


def dataset_info(handle: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="kgnite-dataset-") as tmpdir:
        run_kaggle(["datasets", "metadata", handle, "--path", tmpdir])
        metadata = load_json_file(Path(tmpdir), "dataset-metadata.json")
    return {
        "resource": "dataset",
        "handle": handle,
        "url": handle_url("datasets", handle),
        "metadata": metadata,
        "files": list_files("datasets", handle),
    }


def competition_info(handle: str) -> dict[str, Any]:
    return {
        "resource": "competition",
        "handle": handle,
        "url": handle_url("competitions", handle),
        "files": list_files("competitions", handle),
    }


def kernel_info(handle: str) -> dict[str, Any]:
    status_output = run_kaggle(["kernels", "status", handle], check=False)
    return {
        "resource": "notebook",
        "handle": handle,
        "url": handle_url("kernels", handle),
        "status": (status_output.stdout or status_output.stderr).strip(),
        "files": list_files("kernels", handle),
    }


def model_info(handle: str) -> dict[str, Any]:
    parts = handle.split("/")
    with tempfile.TemporaryDirectory(prefix="kgnite-model-") as tmpdir:
        if len(parts) == 2:
            run_kaggle(["models", "get", handle, "--path", tmpdir])
            metadata = load_json_file(Path(tmpdir), "model-metadata.json")
            files: list[dict[str, str]] = []
        elif len(parts) == 4:
            run_kaggle(["models", "instances", "get", handle, "--path", tmpdir])
            metadata = load_json_file(Path(tmpdir), "model-instance-metadata.json")
            files = []
        elif len(parts) == 5:
            metadata = {"version_handle": handle}
            files = list_files("models", handle)
        else:
            raise KgniteError(
                "Model handle must be <owner>/<model>, <owner>/<model>/<framework>/<variation>, "
                "or <owner>/<model>/<framework>/<variation>/<version>."
            )
    return {
        "resource": "model",
        "handle": handle,
        "url": handle_url("models", handle),
        "metadata": metadata,
        "files": files,
    }


def command_info(args: argparse.Namespace) -> int:
    resource = normalize_resource(args.resource)
    validate_resource_handle(resource, args.handle)
    if resource == "datasets":
        payload = dataset_info(args.handle)
    elif resource == "competitions":
        payload = competition_info(args.handle)
    elif resource == "kernels":
        payload = kernel_info(args.handle)
    elif resource == "models":
        payload = model_info(args.handle)
    else:
        raise KgniteError(f"Unsupported resource: {resource}")

    if args.json:
        print_json(payload)
    else:
        print_json(payload)
    return 0


def command_files(args: argparse.Namespace) -> int:
    resource = normalize_resource(args.resource)
    validate_resource_handle(resource, args.handle)
    rows = list_files(
        resource, args.handle, page_size=args.page_size, page_token=args.page_token
    )
    if args.json:
        print_json(rows)
    else:
        print_table(rows)
    return 0


def command_download(args: argparse.Namespace) -> int:
    handle_resource = (
        "notebook" if args.resource == "notebook-output" else args.resource
    )
    validate_resource_handle(handle_resource, args.handle)
    hub = require_kagglehub()
    output_dir = (
        str(Path(args.output_dir).expanduser().resolve()) if args.output_dir else None
    )
    downloaded_path: str

    if args.resource == "dataset":
        downloaded_path = hub.dataset_download(
            args.handle,
            path=args.path,
            force_download=args.force,
            output_dir=output_dir,
        )
    elif args.resource == "competition":
        downloaded_path = hub.competition_download(
            args.handle,
            path=args.path,
            force_download=args.force,
            output_dir=output_dir,
        )
    elif args.resource == "model":
        downloaded_path = hub.model_download(
            args.handle,
            path=args.path,
            force_download=args.force,
            output_dir=output_dir,
        )
    elif args.resource == "notebook-output":
        downloaded_path = hub.notebook_output_download(
            args.handle,
            path=args.path,
            force_download=args.force,
            output_dir=output_dir,
        )
    else:
        raise KgniteError(f"Unsupported download resource: {args.resource}")

    payload = {
        "resource": args.resource,
        "handle": args.handle,
        "path": downloaded_path,
    }
    if args.json:
        print_json(payload)
    else:
        print(f"Downloaded to: {downloaded_path}")
    return 0


def command_preview(args: argparse.Namespace) -> int:
    if args.rows < 1:
        raise KgniteError("--rows must be at least 1.")
    if str(args.columns).casefold() == "all":
        column_limit = None
    else:
        try:
            column_limit = int(args.columns)
        except ValueError as exc:
            raise KgniteError("--columns must be a positive number or `all`.") from exc
        if column_limit < 1:
            raise KgniteError("--columns must be a positive number or `all`.")
    if args.max_file_size_mb <= 0:
        raise KgniteError("--max-file-size-mb must be greater than zero.")
    max_bytes = int(args.max_file_size_mb * 1024 * 1024)

    with tempfile.TemporaryDirectory(prefix="kgnite-preview-") as tmpdir:
        if args.resource == "dataset":
            validate_resource_handle("dataset", args.source)
            files = list_files("datasets", args.source)
            try:
                remote_path, reported_size = choose_preview_file(
                    files, args.path, max_bytes=max_bytes
                )
            except ValueError as exc:
                raise KgniteError(str(exc)) from exc
            downloaded = _download_preview_dataset(
                args.source,
                remote_path,
                tmpdir,
                force=args.force,
                quiet=args.json,
            )
            downloaded_path = Path(downloaded)
            if not downloaded_path.is_file():
                exact = downloaded_path / remote_path
                matches = list(downloaded_path.rglob(Path(remote_path).name))
                downloaded_path = (
                    exact if exact.is_file() else matches[0] if matches else exact
                )
            source_label = args.source
            file_label = remote_path
        elif args.resource == "local":
            requested = Path(args.source).expanduser()
            if not requested.is_absolute():
                raise KgniteError(
                    "Local preview requires an absolute workstation path."
                )
            downloaded_path = requested.resolve()
            if not downloaded_path.is_file():
                raise KgniteError(
                    f"Local preview file does not exist: {downloaded_path}"
                )
            reported_size = downloaded_path.stat().st_size
            source_label = str(downloaded_path)
            file_label = downloaded_path.name
        else:
            downloaded_path, reported_size = _download_preview_url(
                args.source, Path(tmpdir), max_bytes=max_bytes
            )
            source_label = args.source
            file_label = downloaded_path.name
        if not downloaded_path.is_file():
            raise KgniteError(f"Preview file could not be located: {source_label}")
        actual_size = downloaded_path.stat().st_size
        if actual_size > max_bytes:
            raise KgniteError(
                f"File is {actual_size / 1024 / 1024:.1f} MB, above the preview limit of "
                f"{args.max_file_size_mb:g} MB."
            )
        try:
            preview = preview_local_file(
                downloaded_path, row_limit=args.rows, column_limit=column_limit
            )
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise KgniteError(f"Could not preview `{file_label}`: {exc}") from exc

    payload = {
        "resource": args.resource,
        "source": source_label,
        "file": file_label,
        "file_size": reported_size if reported_size is not None else actual_size,
        "row_limit": args.rows,
        "column_limit": "all" if column_limit is None else column_limit,
        **preview,
    }
    if args.json:
        print_json(payload)
    else:
        print(f"Source: {source_label}")
        print(f"File: {file_label}")
        print(
            f"Shape: {preview['shape']['rows']} rows × {preview['shape']['columns']} columns"
        )
        print(f"Columns: {', '.join(preview['columns'])}")
        print_table(preview["rows"])
    return 0


def _download_preview_dataset(
    handle: str, remote_path: str, output_dir: str, *, force: bool, quiet: bool
) -> str:
    hub_logger = logging.getLogger("kagglehub")
    previous_level = hub_logger.level
    if quiet:
        hub_logger.setLevel(logging.CRITICAL)
    try:
        with (
            contextlib.redirect_stdout(io.StringIO())
            if quiet
            else contextlib.nullcontext(),
            contextlib.redirect_stderr(io.StringIO())
            if quiet
            else contextlib.nullcontext(),
        ):
            return require_kagglehub().dataset_download(
                handle, path=remote_path, force_download=force, output_dir=output_dir
            )
    finally:
        hub_logger.setLevel(previous_level)


def _download_preview_url(
    url: str, output_dir: Path, *, max_bytes: int
) -> tuple[Path, int]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise KgniteError("Remote preview URL must use http:// or https://.")
    request = urllib.request.Request(url, headers={"User-Agent": "kgnite-preview/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            final_scheme = urllib.parse.urlparse(response.geturl()).scheme
            if final_scheme not in {"http", "https"}:
                raise KgniteError("Remote URL redirected to an unsupported scheme.")
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                raise KgniteError(
                    f"Remote file is {int(content_length) / 1024 / 1024:.1f} MB, above the preview limit."
                )
            name = Path(urllib.parse.unquote(parsed.path)).name or "preview"
            suffix = Path(name).suffix.lower()
            if suffix not in {".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".txt"}:
                content_type = response.headers.get_content_type()
                suffix = {
                    "text/csv": ".csv",
                    "application/json": ".json",
                    "text/plain": ".txt",
                }.get(content_type, "")
                name += suffix
            destination = output_dir / name
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise KgniteError(
                    "Remote file exceeded the preview limit while downloading."
                )
            destination.write_bytes(data)
            return destination, len(data)
    except (OSError, ValueError) as exc:
        if isinstance(exc, KgniteError):
            raise
        raise KgniteError(f"Could not fetch remote preview URL: {exc}") from exc


def command_pull_notebook(args: argparse.Namespace) -> int:
    validate_resource_handle("notebook", args.handle)
    command = ["kernels", "pull", args.handle]
    if args.output_dir:
        command += ["--path", str(Path(args.output_dir).expanduser().resolve())]
    result = run_kaggle(command)
    output = (result.stdout or result.stderr).strip()
    if args.json:
        print_json(
            {"resource": "notebook-code", "handle": args.handle, "result": output}
        )
    else:
        print(output)
    return 0


def command_settings(args: argparse.Namespace) -> int:
    updates = {
        "workspace_dir": args.workspace_dir,
        "competitions_dir": args.competitions_dir,
        "projects_dir": args.projects_dir,
        "kaggle_username": args.kaggle_username,
        "default_dataset_license": args.default_dataset_license,
    }
    try:
        payload = save_settings(updates) if any(value is not None for value in updates.values()) else load_settings()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise KgniteError(f"Could not update settings: {exc}") from exc
    print_json(payload)
    return 0


def command_create_project(args: argparse.Namespace) -> int:
    directory = Path(args.directory) if args.directory else workspace_subdir("project", args.name)
    try:
        payload = create_project_workspace(
            args.name,
            directory,
            dataset_sources=args.dataset_source,
            kernel_sources=args.kernel_source,
            model_sources=args.model_source,
            force=args.force,
        )
        if args.template:
            notebook = write_starter_notebook(
                args.name,
                directory / "notebooks" / f"{args.name}-01.ipynb",
                directory / "data",
                participant=args.participant or getpass.getuser(),
                kaggle_data_sources=args.dataset_source or [],
                force=args.force,
            )
            payload["notebook"] = str(notebook)
    except (ValueError, FileExistsError) as exc:
        raise KgniteError(str(exc)) from exc
    print_json(payload)
    return 0


def command_workspace_help(args: argparse.Namespace) -> int:
    directory = (
        Path(args.directory)
        if args.directory
        else workspace_subdir(args.type, args.name)
    ).expanduser().resolve()
    if not directory.is_dir():
        raise KgniteError(f"Workspace directory was not found: {directory}")
    path = write_workspace_help(directory, args.name, project_type=args.type)
    print_json({"workspace": str(directory), "help": str(path), "type": args.type})
    return 0


def command_prepare_notebook(args: argparse.Namespace) -> int:
    notebook = Path(args.notebook).expanduser().resolve()
    settings = load_settings()
    handle_input = (args.handle or "").strip()
    title = (args.title or "").strip()
    notices = []
    try:
        if title:
            slug = kaggle_notebook_slug(title)
        elif handle_input:
            handle_parts = [part for part in handle_input.split("/") if part]
            if len(handle_parts) < 2:
                raise KgniteError("Notebook handle must be `owner/notebook-slug`.")
            title = notebook_title_from_slug(handle_parts[1])
            slug = kaggle_notebook_slug(title)
        else:
            title = notebook.stem.replace("-", " ").replace("_", " ").title()
            slug = kaggle_notebook_slug(title)
    except ValueError as exc:
        raise KgniteError(str(exc)) from exc
    if handle_input:
        owner = handle_input.split("/", 1)[0]
        handle_slug = handle_input.split("/", 1)[1] if "/" in handle_input else ""
        handle = f"{owner}/{slug}"
        if handle_slug and handle_slug != slug:
            notices.append(
                f"Adjusted notebook handle to {handle} so the slug matches the title."
            )
    else:
        owner = str(settings.get("kaggle_username") or "").strip()
        if not owner:
            raise KgniteError(
                "--handle is required when settings kaggle_username is empty."
            )
        handle = f"{owner}/{slug}"
        notices.append(f"Derived notebook handle from title: {handle}")
    validate_resource_handle("notebook", handle)
    project_dir = notebook.parent.parent if notebook.parent.name == "notebooks" else notebook.parent
    output_dir = Path(args.output_dir) if args.output_dir else project_dir / "kaggle-notebooks" / slug
    dataset_sources = list(args.dataset_source or [])
    competition_sources = list(args.competition_source or [])
    if args.competition and args.competition not in competition_sources:
        competition_sources.append(args.competition)
    local_dataset_payload = None
    try:
        if args.local_dataset:
            if not args.dataset_handle:
                raise ValueError("--dataset-handle is required with --local-dataset.")
            validate_resource_handle("dataset", args.dataset_handle)
            if args.dataset_handle not in dataset_sources:
                dataset_sources.append(args.dataset_handle)
            dataset_slug = args.dataset_handle.split("/", 1)[1]
            dataset_output = project_dir / "kaggle-datasets" / dataset_slug
            local_dataset_payload = prepare_local_dataset_bundle(
                Path(args.local_dataset),
                dataset_output,
                handle=args.dataset_handle,
                title=args.dataset_title or dataset_slug.replace("-", " ").title(),
                license_name=args.dataset_license or settings["default_dataset_license"],
                force=args.force,
            )
        payload = prepare_kaggle_notebook_bundle(
            notebook,
            output_dir,
            handle=handle,
            title=title,
            competition=args.competition,
            dataset_sources=dataset_sources,
            competition_sources=competition_sources,
            kernel_sources=args.kernel_source,
            model_sources=args.model_source,
            public=args.public,
            enable_internet=args.enable_internet,
            enable_gpu=args.enable_gpu,
            force=args.force,
        )
        if local_dataset_payload:
            payload["local_dataset"] = local_dataset_payload
            payload["push_command"] += " --with-datasets"
        if notices:
            payload["notices"] = notices
    except (ValueError, FileExistsError) as exc:
        raise KgniteError(str(exc)) from exc
    print_json(payload)
    return 0


def command_push_notebook(args: argparse.Namespace) -> int:
    bundle_dir = Path(args.bundle_dir).expanduser().resolve()
    metadata = bundle_dir / "kernel-metadata.json"
    if not metadata.is_file():
        raise KgniteError(f"Kaggle notebook metadata was not found: {metadata}")
    pushed_datasets = []
    if args.with_datasets:
        try:
            notebook_metadata = json.loads(metadata.read_text())
        except json.JSONDecodeError as exc:
            raise KgniteError(f"Invalid Kaggle notebook metadata: {metadata}") from exc
        project_dir = bundle_dir.parent.parent
        dataset_root = project_dir / "kaggle-datasets"
        wanted = set(notebook_metadata.get("dataset_sources", []))
        if dataset_root.is_dir():
            for dataset_metadata in sorted(dataset_root.glob("*/dataset-metadata.json")):
                details = json.loads(dataset_metadata.read_text())
                if details.get("id") not in wanted:
                    continue
                dataset_command = [
                    "datasets",
                    args.dataset_action,
                    "--path",
                    str(dataset_metadata.parent),
                ]
                if args.dataset_action == "create" and args.public_datasets:
                    dataset_command.append("--public")
                dataset_result = run_kaggle(dataset_command)
                pushed_datasets.append(
                    {
                        "handle": details["id"],
                        "bundle_dir": str(dataset_metadata.parent),
                        "result": (dataset_result.stdout or dataset_result.stderr).strip(),
                    }
                )
    command = ["kernels", "push", "--path", str(bundle_dir)]
    if args.timeout:
        command += ["--timeout", str(args.timeout)]
    if args.accelerator:
        command += ["--accelerator", args.accelerator]
    result = run_kaggle(command)
    payload = {"bundle_dir": str(bundle_dir), "datasets": pushed_datasets, "result": (result.stdout or result.stderr).strip()}
    print_json(payload) if args.json else print(payload["result"])
    return 0


def command_submit(args: argparse.Namespace) -> int:
    if not args.file and not args.kernel:
        raise KgniteError(
            "Provide either --file or --kernel for a competition submission."
        )
    command = ["competitions", "submit", args.competition, "--message", args.message]
    if args.file:
        command += ["--file", str(Path(args.file).expanduser().resolve())]
    if args.kernel:
        command += ["--kernel", args.kernel]
    if args.version:
        command += ["--version", str(args.version)]
    result = run_kaggle(command)
    output = (result.stdout or result.stderr).strip()
    if args.json:
        print_json({"competition": args.competition, "result": output})
    else:
        print(output)
    return 0


def command_leaderboard(args: argparse.Namespace) -> int:
    command = ["competitions", "leaderboard", args.competition, "--csv"]
    if args.show or not args.download:
        command.append("--show")
    if args.download:
        command.append("--download")
    if args.output_dir:
        command += ["--path", str(Path(args.output_dir).expanduser().resolve())]
    if args.page_size:
        command += ["--page-size", str(args.page_size)]
    if args.page_token:
        command += ["--page-token", args.page_token]

    result = run_kaggle(command)
    output = result.stdout.strip()
    if args.download:
        payload = {
            "competition": args.competition,
            "output_dir": args.output_dir or os.getcwd(),
            "result": output,
        }
        if args.json:
            print_json(payload)
        else:
            print(output)
        return 0

    rows = parse_csv_output(output)
    if args.json:
        print_json(rows)
    else:
        print_table(rows)
    return 0


def command_submissions(args: argparse.Namespace) -> int:
    command = ["competitions", "submissions", args.competition, "--csv"]
    try:
        result = run_kaggle(command)
    except KgniteError as exc:
        message = str(exc)
        if "ListSubmissions" in message or "400 Client Error" in message:
            friendly = {
                "competition": args.competition,
                "hint": (
                    "Kaggle did not return submission history. Likely causes: you have not joined the competition, "
                    "you have no submissions yet, or the API is rejecting submission-history access for this competition/account."
                ),
                "next_steps": [
                    f"Open https://www.kaggle.com/competitions/{args.competition}",
                    "Accept the competition rules if required.",
                    "Create a submission, then rerun `kgnite submissions`.",
                ],
                "upstream_error": message,
            }
            if args.json:
                print_json(friendly)
            else:
                print_json(friendly)
            return 0
        raise
    rows = parse_csv_output(result.stdout)
    if args.json:
        print_json(rows)
    else:
        print_table(rows)
    return 0


def command_upload_dataset(args: argparse.Namespace) -> int:
    local_dir = str(Path(args.local_dir).expanduser().resolve())
    if args.handle:
        require_kagglehub().dataset_upload(
            args.handle,
            local_dir,
            version_notes=args.message or "",
            ignore_patterns=args.ignore,
        )
        output = {
            "resource": "dataset",
            "mode": "kagglehub",
            "handle": args.handle,
            "local_dir": local_dir,
        }
    else:
        command = [
            "datasets",
            "version" if args.version else "create",
            "--path",
            local_dir,
        ]
        if args.message:
            command += ["--message", args.message]
        if args.public:
            command.append("--public")
        if args.keep_tabular:
            command.append("--keep-tabular")
        if args.dir_mode:
            command += ["--dir-mode", args.dir_mode]
        if args.delete_old_versions and args.version:
            command.append("--delete-old-versions")
        result = run_kaggle(command)
        output = {
            "resource": "dataset",
            "mode": "kaggle-cli",
            "local_dir": local_dir,
            "result": (result.stdout or result.stderr).strip(),
        }

    if args.json:
        print_json(output)
    else:
        print_json(output)
    return 0


def command_upload_model(args: argparse.Namespace) -> int:
    local_dir = str(Path(args.local_dir).expanduser().resolve())
    if args.handle:
        require_kagglehub().model_upload(
            args.handle,
            local_dir,
            license_name=args.license_name,
            version_notes=args.message or "",
            ignore_patterns=args.ignore,
            sigstore=args.sigstore,
        )
        output = {
            "resource": "model",
            "mode": "kagglehub",
            "handle": args.handle,
            "local_dir": local_dir,
        }
    else:
        command = ["models", args.action, "--path", local_dir]
        result = run_kaggle(command)
        output = {
            "resource": "model",
            "mode": "kaggle-cli",
            "action": args.action,
            "local_dir": local_dir,
            "result": (result.stdout or result.stderr).strip(),
        }

    if args.json:
        print_json(output)
    else:
        print_json(output)
    return 0


def command_usage(_: argparse.Namespace) -> int:
    print_usage_guide()
    return 0


def command_completions(args: argparse.Namespace) -> int:
    shell = args.shell or detect_shell()
    script = shell_completion_script(shell)

    if args.print:
        print(script)
        return 0

    target_dir = completions_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    if shell == "bash":
        target_file = target_dir / "kgnite.bash"
        rc_file = Path.home() / ".bashrc"
        refresh_cmd = f'source "{target_file}"'
    else:
        target_file = target_dir / "_kgnite"
        rc_file = Path.home() / ".zshrc"
        refresh_cmd = (
            f'fpath=("{target_dir}" $fpath); autoload -Uz compinit && compinit'
        )

    target_file.write_text(script)

    payload = {
        "shell": shell,
        "completion_file": str(target_file),
        "rc_file": str(rc_file),
        "refresh_command": refresh_cmd,
    }

    if args.json:
        print_json(payload)
        return 0

    print(f"Detected shell: {shell}")
    print(f"Completion file written to: {target_file}")
    print()
    if shell == "bash":
        print("To enable it now, run:")
        print(f'  source "{target_file}"')
        print()
        print(
            "To make it persistent, add this to your shell config if it is not already there:"
        )
        print(f'  echo \'source "{target_file}"\' >> "{rc_file}"')
    else:
        print("To enable it now, run:")
        print(f'  fpath=("{target_dir}" $fpath)')
        print("  autoload -Uz compinit && compinit")
        print()
        print(
            "To make it persistent, add these lines to your shell config if they are not already there:"
        )
        print(f'  echo \'fpath=("{target_dir}" $fpath)\' >> "{rc_file}"')
        print(f"  echo 'autoload -Uz compinit && compinit' >> \"{rc_file}\"")
    print()
    print(
        "Run `kgnite completions` again after reinstalling if you want to refresh the generated completion file."
    )
    return 0


def infer_handle_from_row(resource: str, row: dict[str, str]) -> str:
    candidates = {
        "datasets": ["ref", "datasetRef", "id", "slug"],
        "competitions": ["ref", "competitionName", "slug"],
        "kernels": ["ref", "kernelRef", "id"],
        "models": ["ref", "modelRef", "id"],
    }
    for key in candidates.get(resource, []):
        value = row.get(key)
        if value:
            return normalize_handle(resource, value)
    raise KgniteError(f"Could not infer handle from search result: {row}")


def normalize_handle(resource: str, value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("https://www.kaggle.com/"):
        parts = cleaned.removeprefix("https://www.kaggle.com/").split("/")
        if (
            resource == "competitions"
            and len(parts) >= 2
            and parts[0] == "competitions"
        ):
            return parts[1]
        if resource == "datasets" and len(parts) >= 3 and parts[0] == "datasets":
            return f"{parts[1]}/{parts[2]}"
        if resource == "kernels" and len(parts) >= 3 and parts[0] == "code":
            return f"{parts[1]}/{parts[2]}"
        if resource == "models" and len(parts) >= 3 and parts[0] == "models":
            return "/".join(parts[1:])
    return cleaned


def build_info_args(resource: str, handle: str) -> argparse.Namespace:
    mapped = {
        "datasets": "dataset",
        "competitions": "competition",
        "kernels": "notebook",
        "models": "model",
    }[resource]
    return argparse.Namespace(resource=mapped, handle=handle, json=False)


def build_files_args(resource: str, handle: str) -> argparse.Namespace:
    mapped = {
        "datasets": "dataset",
        "competitions": "competition",
        "kernels": "notebook",
        "models": "model",
    }[resource]
    return argparse.Namespace(
        resource=mapped, handle=handle, page_size=None, page_token=None, json=False
    )


def command_browse(args: argparse.Namespace) -> int:
    print("Interactive browse mode")
    print(
        "Step 1: choose a resource from the menu below using a number or text, or type a search query directly."
    )
    print(
        "If you type a normal query like `llm` or `gemma`, kgnite will use `datasets` as the default resource."
    )
    print("Step 2: pick a result number.")
    print("Step 3: choose an action such as info, files, or download.")
    print()
    print("Resource options:")
    print("  1. datasets")
    print("  2. competitions")
    print("  3. kernels")
    print("  4. models")
    print()

    default_resource = normalize_resource(args.resource or "datasets")
    first_value = prompt("Enter number, resource, or search query", default="1")
    normalized_resource = try_normalize_resource(first_value)
    if first_value in {"1", "2", "3", "4"}:
        resource = {
            "1": "datasets",
            "2": "competitions",
            "3": "kernels",
            "4": "models",
        }[first_value]
        print(f"Selected resource: {resource}")
        query = prompt("Search query", default=args.search or "")
    elif normalized_resource:
        resource = normalized_resource
        print(f"Selected resource: {resource}")
        query = prompt("Search query", default=args.search or "")
    else:
        resource = default_resource
        query = first_value

    if not query and (first_value in {"1", "2", "3", "4"} or normalized_resource):
        print(f"Selected resource: {resource}")
        print("Now enter a search query such as: titanic, llm, rag, gemma")
        query = prompt("Search query")

    if not query:
        print("No search query entered.")
        print("Try: kgnite browse --resource datasets --search titanic")
        print("Or rerun and enter a query such as: titanic, llm, rag, gemma")
        return 0
    search_args = argparse.Namespace(
        resource=resource,
        search=query or None,
        sort_by=args.sort_by,
        page=args.page,
        page_size=args.page_size,
        owner=None,
        user=None,
        category=None,
        group=None,
        language=None,
        kernel_type=None,
        output_type=None,
        dataset=None,
        competition=None,
        json=False,
    )
    rows = search_rows(search_args)
    if not rows:
        print("No results.")
        return 0

    indexed_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows[: args.limit], start=1):
        indexed_rows.append({"index": index, **row})
    print_table(indexed_rows)

    raw_choice = prompt("Pick result number", default="1")
    try:
        choice = int(raw_choice)
    except ValueError as exc:
        raise KgniteError("Browse choice must be a number.") from exc
    if choice < 1 or choice > len(indexed_rows):
        raise KgniteError("Browse choice is out of range.")

    selected = indexed_rows[choice - 1]
    handle = infer_handle_from_row(resource, selected)
    print(f"Selected: {handle}")

    available_actions = ["info", "files"]
    if resource in {"datasets", "competitions", "models"}:
        available_actions.append("download")
    if resource == "kernels":
        available_actions += ["download-output", "pull-source"]
    action = prompt(f"Action ({'/'.join(available_actions)})", default="info")

    if action == "info":
        return command_info(build_info_args(resource, handle))
    if action == "files":
        return command_files(build_files_args(resource, handle))
    if action == "download":
        mapped = {
            "datasets": "dataset",
            "competitions": "competition",
            "models": "model",
        }[resource]
        destination = download_target_dir(
            resource, handle, choose_download_destination(resource)
        )
        return command_download(
            argparse.Namespace(
                resource=mapped,
                handle=handle,
                path=None,
                output_dir=destination,
                force=False,
                json=False,
            )
        )
    if action == "download-output" and resource == "kernels":
        destination = download_target_dir(
            resource, handle, choose_download_destination(resource)
        )
        return command_download(
            argparse.Namespace(
                resource="notebook-output",
                handle=handle,
                path=None,
                output_dir=destination,
                force=False,
                json=False,
            )
        )
    if action == "pull-source" and resource == "kernels":
        destination = download_target_dir(
            resource, handle, choose_download_destination(resource)
        )
        return command_pull_notebook(
            argparse.Namespace(handle=handle, output_dir=destination, json=False)
        )

    raise KgniteError(f"Unsupported browse action: {action}")


def build_parser() -> argparse.ArgumentParser:
    parser = KgniteArgumentParser(
        prog=APP_NAME,
        description="Unified Kaggle helper for search, metadata, files, downloads, and notebook pulls.",
        epilog=textwrap.dedent(USAGE_TEXT),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(
        dest="command", required=True, parser_class=KgniteArgumentParser
    )

    usage_parser = subparsers.add_parser(
        "usage", help="Show example workflows and common command patterns."
    )
    usage_parser.set_defaults(func=command_usage)

    completions_parser = subparsers.add_parser(
        "completions", help="Install or print shell completion setup."
    )
    completions_parser.add_argument(
        "--shell",
        choices=["bash", "zsh"],
        help="Shell type. Default is auto-detected from $SHELL.",
    )
    completions_parser.add_argument(
        "--print",
        action="store_true",
        help="Print the completion script instead of installing it.",
    )
    add_common_output_flags(completions_parser)
    completions_parser.set_defaults(func=command_completions)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Inspect local Kaggle/KaggleHub availability and authentication state.",
    )
    add_common_output_flags(doctor_parser)
    doctor_parser.set_defaults(func=command_doctor)

    settings_parser = subparsers.add_parser(
        "settings", help="Show or update persistent kgnite settings."
    )
    settings_parser.add_argument("--workspace-dir")
    settings_parser.add_argument("--competitions-dir")
    settings_parser.add_argument("--projects-dir")
    settings_parser.add_argument("--kaggle-username")
    settings_parser.add_argument("--default-dataset-license")
    add_common_output_flags(settings_parser)
    settings_parser.set_defaults(func=command_settings)

    project_parser = subparsers.add_parser(
        "create-project", help="Create a generic Kaggle-ready project workspace."
    )
    project_parser.add_argument("name")
    project_parser.add_argument("--directory")
    project_parser.add_argument("--participant")
    project_parser.add_argument("--dataset-source", action="append")
    project_parser.add_argument("--kernel-source", action="append")
    project_parser.add_argument("--model-source", action="append")
    project_parser.add_argument(
        "--template", action=argparse.BooleanOptionalAction, default=True
    )
    project_parser.add_argument("--force", action="store_true")
    add_common_output_flags(project_parser)
    project_parser.set_defaults(func=command_create_project)

    workspace_help_parser = subparsers.add_parser(
        "workspace-help", help="Create or refresh a workspace README.md guide."
    )
    workspace_help_parser.add_argument("name")
    workspace_help_parser.add_argument(
        "--type", choices=["competition", "project"], required=True
    )
    workspace_help_parser.add_argument("--directory")
    add_common_output_flags(workspace_help_parser)
    workspace_help_parser.set_defaults(func=command_workspace_help)

    search_parser = subparsers.add_parser("search", help="Search Kaggle resources.")
    search_parser.add_argument(
        "resource", choices=["datasets", "competitions", "kernels", "models"]
    )
    search_parser.add_argument("search", nargs="?", help="Search text.")
    search_parser.add_argument("--sort-by")
    search_parser.add_argument("--page", type=int)
    search_parser.add_argument("--page-size", type=int)
    search_parser.add_argument("--owner")
    search_parser.add_argument("--user")
    search_parser.add_argument("--category")
    search_parser.add_argument("--group")
    search_parser.add_argument("--language")
    search_parser.add_argument("--kernel-type")
    search_parser.add_argument("--output-type")
    search_parser.add_argument("--dataset")
    search_parser.add_argument("--competition")
    search_parser.add_argument(
        "--tag",
        action="append",
        help="Require a tag in the returned metadata. Repeatable.",
    )
    search_parser.add_argument(
        "--keyword",
        action="append",
        help="Require a keyword in the returned metadata. Repeatable.",
    )
    add_common_output_flags(search_parser)
    search_parser.set_defaults(func=command_search)

    setup_parser = subparsers.add_parser(
        "setup", help="Interactively create a local competition workspace."
    )
    setup_parser.add_argument("competition", nargs="?", help="Kaggle competition slug.")
    setup_parser.add_argument(
        "--directory", help="Workspace directory. Defaults to the competition slug."
    )
    setup_parser.add_argument(
        "--metric", help="Score metric name stored in the workspace configuration."
    )
    setup_parser.add_argument(
        "--participant",
        help="Participant name written into generated notebook metadata.",
    )
    setup_parser.add_argument(
        "--competition-notes",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include official Kaggle competition notes in the generated notebook.",
    )
    setup_parser.add_argument(
        "--notes-page",
        action="append",
        help="Competition page to include, such as data-description or evaluation. Repeatable.",
    )
    setup_parser.add_argument(
        "--lower-is-better", action=argparse.BooleanOptionalAction, default=None
    )
    setup_parser.add_argument(
        "--download", action=argparse.BooleanOptionalAction, default=None
    )
    setup_parser.add_argument(
        "--template", action=argparse.BooleanOptionalAction, default=None
    )
    setup_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace generated files and refresh downloads.",
    )
    add_common_output_flags(setup_parser)
    setup_parser.set_defaults(func=command_setup)

    template_parser = subparsers.add_parser(
        "template", help="Generate a starter competition notebook."
    )
    template_parser.add_argument("competition", help="Kaggle competition slug.")
    template_parser.add_argument(
        "--output",
        help="Notebook path. Defaults to the next available <competition>-NN.ipynb.",
    )
    template_parser.add_argument(
        "--data-dir",
        default="./data",
        help="Competition data directory used by the notebook.",
    )
    template_parser.add_argument(
        "--participant",
        help="Participant name. Defaults to KGNITE_PARTICIPANT or the local user.",
    )
    template_parser.add_argument(
        "--competition-notes",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include official Kaggle competition notes.",
    )
    template_parser.add_argument(
        "--notes-page",
        action="append",
        help="Competition page to include. Repeatable; defaults to data-description.",
    )
    template_parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing notebook."
    )
    add_common_output_flags(template_parser)
    template_parser.set_defaults(func=command_template)

    performance_parser = subparsers.add_parser(
        "performance", help="Track and visualize submission scores over time."
    )
    performance_parser.add_argument("competition", help="Kaggle competition slug.")
    performance_parser.add_argument(
        "--sync",
        action="store_true",
        help="Fetch and merge current Kaggle submissions.",
    )
    performance_parser.add_argument("--history", help="Local JSON history path.")
    performance_parser.add_argument(
        "--lower-is-better",
        action="store_true",
        help="Treat the minimum score as best.",
    )
    add_common_output_flags(performance_parser)
    performance_parser.set_defaults(func=command_performance)

    trending_parser = subparsers.add_parser(
        "trending", help="Show popular or newly added Kaggle resources."
    )
    trending_parser.add_argument(
        "resource", choices=["datasets", "competitions", "kernels", "models"]
    )
    trending_parser.add_argument(
        "--order", choices=["popular", "new"], default="popular"
    )
    trending_parser.add_argument("--search", help="Optional upstream search query.")
    trending_parser.add_argument(
        "--tag", action="append", help="Require a tag. Repeatable."
    )
    trending_parser.add_argument(
        "--keyword", action="append", help="Require a keyword. Repeatable."
    )
    trending_parser.add_argument("--category", help="Competition category.")
    trending_parser.add_argument("--limit", type=int, default=10)
    add_common_output_flags(trending_parser)
    trending_parser.set_defaults(func=command_trending)

    web_parser = subparsers.add_parser(
        "web", help="Launch a temporary localhost web app in the default browser."
    )
    web_parser.add_argument(
        "--port", type=int, default=0, help="Local port. Defaults to an available port."
    )
    web_parser.add_argument(
        "--browser",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Open the default browser. Use --no-browser to print the URL only.",
    )
    web_parser.add_argument(
        "--heartbeat-timeout",
        type=float,
        default=30.0,
        help="Seconds without a page heartbeat before shutdown.",
    )
    web_parser.add_argument(
        "--command-timeout",
        type=float,
        default=300.0,
        help="Maximum seconds allowed for one web-triggered command.",
    )
    web_parser.set_defaults(func=command_web)

    info_parser = subparsers.add_parser(
        "info", help="Show metadata and related information for a resource."
    )
    info_parser.add_argument(
        "resource", choices=["dataset", "competition", "notebook", "model"]
    )
    info_parser.add_argument("handle")
    add_common_output_flags(info_parser)
    info_parser.set_defaults(func=command_info)

    files_parser = subparsers.add_parser(
        "files",
        help="List files for a dataset, competition, notebook, or model version.",
    )
    files_parser.add_argument(
        "resource", choices=["dataset", "competition", "notebook", "model"]
    )
    files_parser.add_argument("handle")
    files_parser.add_argument("--page-size", type=int)
    files_parser.add_argument("--page-token")
    add_common_output_flags(files_parser)
    files_parser.set_defaults(func=command_files)

    download_parser = subparsers.add_parser(
        "download", help="Download Kaggle assets using kagglehub."
    )
    download_parser.add_argument(
        "resource", choices=["dataset", "competition", "model", "notebook-output"]
    )
    download_parser.add_argument("handle")
    download_parser.add_argument(
        "--path", help="Specific file path within the remote resource."
    )
    download_parser.add_argument(
        "--output-dir", help="Target directory for the downloaded files."
    )
    download_parser.add_argument(
        "--force", action="store_true", help="Force a fresh download."
    )
    add_common_output_flags(download_parser)
    download_parser.set_defaults(func=command_download)

    preview_parser = subparsers.add_parser(
        "preview",
        help="Preview rows from one dataset file without downloading the full dataset.",
    )
    preview_parser.add_argument(
        "resource", choices=["dataset", "local", "url"], help="Preview source type."
    )
    preview_parser.add_argument(
        "source", help="Dataset handle, absolute local path, or HTTP/HTTPS URL."
    )
    preview_parser.add_argument(
        "--path", help="Specific remote CSV, TSV, JSON, JSONL, or text file."
    )
    preview_parser.add_argument(
        "--rows", type=int, default=10, help="Maximum rows to display."
    )
    preview_parser.add_argument(
        "--columns", default="10", help="Maximum columns to display, or `all`."
    )
    preview_parser.add_argument(
        "--max-file-size-mb",
        type=float,
        default=25.0,
        help="Refuse files larger than this limit. Defaults to 25 MB.",
    )
    preview_parser.add_argument(
        "--force", action="store_true", help="Refresh the selected cached file."
    )
    add_common_output_flags(preview_parser)
    preview_parser.set_defaults(func=command_preview)

    pull_parser = subparsers.add_parser(
        "pull-notebook", help="Pull notebook source files via the Kaggle CLI."
    )
    pull_parser.add_argument("handle")
    pull_parser.add_argument("--output-dir")
    add_common_output_flags(pull_parser)
    pull_parser.set_defaults(func=command_pull_notebook)

    prepare_notebook_parser = subparsers.add_parser(
        "prepare-notebook",
        help="Prepare a project-local Kaggle Notebook upload bundle.",
    )
    prepare_notebook_parser.add_argument("notebook", help="Local .ipynb file.")
    prepare_notebook_parser.add_argument(
        "--handle",
        help=(
            "Kaggle notebook owner/slug. If --title is also supplied, the slug is "
            "derived from the title and this value only supplies the owner."
        ),
    )
    prepare_notebook_parser.add_argument("--competition", help="Linked competition slug.")
    prepare_notebook_parser.add_argument("--dataset-source", action="append")
    prepare_notebook_parser.add_argument("--competition-source", action="append")
    prepare_notebook_parser.add_argument("--kernel-source", action="append")
    prepare_notebook_parser.add_argument("--model-source", action="append")
    prepare_notebook_parser.add_argument("--local-dataset")
    prepare_notebook_parser.add_argument("--dataset-handle")
    prepare_notebook_parser.add_argument("--dataset-title")
    prepare_notebook_parser.add_argument("--dataset-license")
    prepare_notebook_parser.add_argument(
        "--title",
        help=(
            "Public notebook title. If --handle is omitted, the handle is derived "
            "from this title and the configured Kaggle username."
        ),
    )
    prepare_notebook_parser.add_argument("--output-dir", help="Bundle destination.")
    prepare_notebook_parser.add_argument(
        "--public", action="store_true", help="Prepare a public notebook."
    )
    prepare_notebook_parser.add_argument("--enable-internet", action="store_true")
    prepare_notebook_parser.add_argument("--enable-gpu", action="store_true")
    prepare_notebook_parser.add_argument("--force", action="store_true")
    add_common_output_flags(prepare_notebook_parser)
    prepare_notebook_parser.set_defaults(func=command_prepare_notebook)

    push_notebook_parser = subparsers.add_parser(
        "push-notebook", help="Create or update a prepared Kaggle Notebook."
    )
    push_notebook_parser.add_argument("bundle_dir")
    push_notebook_parser.add_argument("--timeout", type=int)
    push_notebook_parser.add_argument("--accelerator")
    push_notebook_parser.add_argument(
        "--with-datasets", action="store_true", help="Push matching staged local datasets first."
    )
    push_notebook_parser.add_argument(
        "--dataset-action", choices=["create", "version"], default="create"
    )
    push_notebook_parser.add_argument(
        "--public-datasets", action=argparse.BooleanOptionalAction, default=True
    )
    add_common_output_flags(push_notebook_parser)
    push_notebook_parser.set_defaults(func=command_push_notebook)

    submit_parser = subparsers.add_parser(
        "submit", help="Submit a file or notebook run to a Kaggle competition."
    )
    submit_parser.add_argument("competition")
    submit_parser.add_argument("--file", help="Submission file path.")
    submit_parser.add_argument(
        "--kernel", help="Notebook handle for code competitions."
    )
    submit_parser.add_argument(
        "--version", type=int, help="Notebook version for code competitions."
    )
    submit_parser.add_argument("--message", required=True, help="Submission message.")
    add_common_output_flags(submit_parser)
    submit_parser.set_defaults(func=command_submit)

    leaderboard_parser = subparsers.add_parser(
        "leaderboard", help="Show or download a competition leaderboard."
    )
    leaderboard_parser.add_argument("competition")
    leaderboard_parser.add_argument(
        "--show", action="store_true", help="Show leaderboard rows in the terminal."
    )
    leaderboard_parser.add_argument(
        "--download", action="store_true", help="Download the leaderboard file."
    )
    leaderboard_parser.add_argument("--output-dir")
    leaderboard_parser.add_argument("--page-size", type=int)
    leaderboard_parser.add_argument("--page-token")
    add_common_output_flags(leaderboard_parser)
    leaderboard_parser.set_defaults(func=command_leaderboard)

    submissions_parser = subparsers.add_parser(
        "submissions", help="List your submissions for a competition."
    )
    submissions_parser.add_argument("competition")
    add_common_output_flags(submissions_parser)
    submissions_parser.set_defaults(func=command_submissions)

    upload_dataset_parser = subparsers.add_parser(
        "upload-dataset",
        help="Upload or version a dataset. Use --handle for kagglehub upload, or rely on metadata files for kaggle CLI mode.",
    )
    upload_dataset_parser.add_argument("local_dir")
    upload_dataset_parser.add_argument(
        "--handle", help="Dataset handle for kagglehub upload, e.g. owner/dataset."
    )
    upload_dataset_parser.add_argument(
        "--message", help="Version notes or create message."
    )
    upload_dataset_parser.add_argument(
        "--ignore", nargs="*", help="Ignore patterns for kagglehub upload."
    )
    upload_dataset_parser.add_argument(
        "--version",
        action="store_true",
        help="Use `kaggle datasets version` in CLI mode.",
    )
    upload_dataset_parser.add_argument(
        "--public",
        action="store_true",
        help="Create the dataset as public in CLI mode.",
    )
    upload_dataset_parser.add_argument(
        "--keep-tabular",
        action="store_true",
        help="Keep tabular files in native format in CLI mode.",
    )
    upload_dataset_parser.add_argument("--dir-mode", choices=["skip", "zip", "tar"])
    upload_dataset_parser.add_argument("--delete-old-versions", action="store_true")
    add_common_output_flags(upload_dataset_parser)
    upload_dataset_parser.set_defaults(func=command_upload_dataset)

    upload_model_parser = subparsers.add_parser(
        "upload-model",
        help="Upload a model variation/version. Use --handle for kagglehub upload, or CLI metadata mode for create/update.",
    )
    upload_model_parser.add_argument("local_dir")
    upload_model_parser.add_argument(
        "--handle",
        help="Model variation handle for kagglehub upload, e.g. owner/model/framework/variation.",
    )
    upload_model_parser.add_argument(
        "--message", help="Version notes for kagglehub upload."
    )
    upload_model_parser.add_argument(
        "--license-name",
        help="License name for kagglehub upload when creating a model.",
    )
    upload_model_parser.add_argument(
        "--ignore", nargs="*", help="Ignore patterns for kagglehub upload."
    )
    upload_model_parser.add_argument(
        "--sigstore",
        action="store_true",
        help="Enable sigstore signing in kagglehub mode.",
    )
    upload_model_parser.add_argument(
        "--action",
        choices=["create", "update"],
        default="create",
        help="CLI metadata mode action.",
    )
    add_common_output_flags(upload_model_parser)
    upload_model_parser.set_defaults(func=command_upload_model)

    browse_parser = subparsers.add_parser(
        "browse",
        help="Interactive terminal workflow for search -> inspect -> download.",
    )
    browse_parser.add_argument(
        "--resource", choices=["datasets", "competitions", "kernels", "models"]
    )
    browse_parser.add_argument("--search")
    browse_parser.add_argument("--sort-by")
    browse_parser.add_argument("--page", type=int, default=1)
    browse_parser.add_argument("--page-size", type=int, default=20)
    browse_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="How many search hits to show in the interactive picker.",
    )
    browse_parser.add_argument(
        "--output-dir",
        help="Default destination for interactive downloads or notebook pulls.",
    )
    browse_parser.set_defaults(func=command_browse)

    return parser


def main(argv: list[str] | None = None) -> int:
    effective_argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    if not effective_argv:
        parser.print_help()
        return 0
    args = parser.parse_args(effective_argv)
    try:
        return args.func(args)
    except KgniteError as exc:
        print(f"{APP_NAME}: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"{APP_NAME}: unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
