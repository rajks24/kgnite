from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

import kagglehub
from kagglehub.config import get_kaggle_credentials
from kagglehub.handle import (
    parse_competition_handle,
    parse_dataset_handle,
    parse_model_handle,
    parse_notebook_handle,
)

APP_NAME = "kgtool"
USAGE_TEXT = """\
Common workflows:
  kgtool doctor
  kgtool completions
  kgtool search datasets "vision transformer" --sort-by votes
  kgtool info dataset zillow/zecon
  kgtool files competition titanic
  kgtool download dataset zillow/zecon --output-dir ./downloads
  kgtool pull-notebook owner/notebook --output-dir ./notebooks
  kgtool submit titanic --file ./submission.csv --message "baseline"
  kgtool leaderboard titanic --show
  kgtool upload-dataset ./my-dataset --handle me/my-dataset --message "v1"
  kgtool upload-model ./my-model --handle me/model/pytorch/base --message "v1"
  kgtool browse
"""
COMMAND_HINTS = {
    "kgtool": [
        "kgtool usage",
        "kgtool completions",
        'kgtool search datasets "titanic"',
        "kgtool browse",
    ],
    "kgtool leaderboard": [
        "kgtool leaderboard titanic --show",
        "kgtool leaderboard titanic --download --output-dir ./leaderboards",
    ],
    "kgtool submissions": [
        "kgtool submissions titanic",
        "kgtool submissions titanic --json",
    ],
    "kgtool upload-dataset": [
        "kgtool upload-dataset ./my-dataset --handle yourname/my-dataset --message \"v1\"",
        "kgtool upload-dataset ./my-dataset --version --message \"march refresh\"",
    ],
    "kgtool upload-model": [
        "kgtool upload-model ./my-model --handle yourname/my-model/pytorch/base --message \"v1\"",
        "kgtool upload-model ./my-model --action create",
    ],
    "kgtool browse": [
        "kgtool browse",
        "kgtool browse --resource datasets --search titanic",
        "kgtool browse --resource kernels --search rag --output-dir ./tmp",
    ],
    "kgtool completions": [
        "kgtool completions",
        "kgtool completions --shell zsh",
        "kgtool completions --print",
    ],
}


class KgtoolError(RuntimeError):
    pass


class KgtoolArgumentParser(argparse.ArgumentParser):
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


def run_kaggle(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["kaggle", *args]
    try:
        return subprocess.run(
            command,
            check=check,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise KgtoolError("The `kaggle` CLI is not installed or not on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        message = stderr or stdout or f"`{' '.join(command)}` failed"
        raise KgtoolError(message) from exc


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
        string_row = {header: "" if row.get(header) is None else str(row.get(header)) for header in headers}
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
            print(f"No custom folder entered. Using default cache folder: {default_dir}")
            return default_dir
        return str(Path(custom_dir).expanduser().resolve())

    normalized = try_normalize_resource(choice)
    if normalized:
        print(f"Input `{choice}` looks like a resource, not a folder choice. Using default cache folder: {default_dir}")
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
    return Path.home() / ".local" / "share" / "kgtool" / "completions"


def bash_completion_script() -> str:
    return textwrap.dedent(
        """\
        _kgtool_completions() {
          local cur prev words cword
          _init_completion || return

          local commands="usage doctor completions search info files download pull-notebook submit leaderboard submissions upload-dataset upload-model browse"
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
            search)
              if [[ $cword -eq 2 ]]; then
                COMPREPLY=( $(compgen -W "$resources_plural" -- "$cur") )
                return
              fi
              COMPREPLY=( $(compgen -W "--sort-by --page --page-size --owner --user --category --group --language --kernel-type --output-type --dataset --competition --json" -- "$cur") )
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
            pull-notebook)
              COMPREPLY=( $(compgen -W "--output-dir --json" -- "$cur") )
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

        complete -F _kgtool_completions kgtool
        """
    )


def zsh_completion_script() -> str:
    return textwrap.dedent(
        """\
        #compdef kgtool

        local -a commands
        commands=(
          'usage:Show example workflows'
          'doctor:Inspect auth and runtime state'
          'completions:Install or print shell completions'
          'search:Search Kaggle resources'
          'info:Show resource metadata'
          'files:List resource files'
          'download:Download Kaggle assets'
          'pull-notebook:Pull notebook source'
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
          search)
            if (( CURRENT == 3 )); then
              _values 'resource' $plural_resources
              return
            fi
            _arguments '--sort-by[Sort order]' '--page[Page number]:page:' '--page-size[Page size]:page size:' '--owner[Owner]:owner:' '--user[User]:user:' '--category[Competition category]:category:(all featured research recruitment gettingStarted masters playground)' '--group[Competition group]:group:(general entered inClass)' '--language[Kernel language]:language:(all python r sqlite julia)' '--kernel-type[Kernel type]:type:(all script notebook)' '--output-type[Kernel output type]:type:(all visualizations data)' '--dataset[Dataset filter]:dataset:' '--competition[Competition filter]:competition:' '--json[Print JSON]'
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
          pull-notebook)
            _arguments '--output-dir[Destination]:folder:_files -/' '--json[Print JSON]'
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
    raise KgtoolError(f"Unsupported shell for completions: {shell}")


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
        raise KgtoolError(f"Unsupported resource: {resource}")
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


def handle_url(resource: str, handle: str) -> str:
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
    raise KgtoolError(f"Unsupported resource: {resource}")


def auth_summary() -> dict[str, Any]:
    config_dir = Path(os.environ.get("KAGGLE_CONFIG_DIR", Path.home() / ".kaggle"))
    kaggle_json = config_dir / "kaggle.json"
    credentials = get_kaggle_credentials()
    api_token = os.environ.get("KAGGLE_API_TOKEN")
    kaggle_key = os.environ.get("KAGGLE_KEY")
    kaggle_username = os.environ.get("KAGGLE_USERNAME")

    auth_method = None
    config_view_error = None
    try:
        config_view = run_kaggle(["config", "view"], check=True).stdout.strip().splitlines()
        for line in config_view:
            stripped = line.strip()
            if stripped.startswith("- auth_method:"):
                auth_method = stripped.split(":", 1)[1].strip()
    except KgtoolError as exc:
        config_view_error = str(exc)

    return {
        "kaggle_cli_on_path": shutil.which("kaggle") is not None,
        "kagglehub_version": getattr(kagglehub, "__version__", "unknown"),
        "kaggle_api_token_env": bool(api_token),
        "legacy_env_credentials": bool(kaggle_key and kaggle_username),
        "kaggle_json_exists": kaggle_json.exists(),
        "kaggle_json_path": str(kaggle_json),
        "kagglehub_credentials_detected": credentials is not None,
        "detected_auth_mode": (
            "access_token"
            if credentials and getattr(credentials, "api_key", None)
            else "username_key"
            if credentials and getattr(credentials, "username", None) and getattr(credentials, "key", None)
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
    if getattr(args, "page", None) is not None and resource in {"datasets", "competitions", "kernels"}:
        command += ["--page", str(args.page)]
    if getattr(args, "page_size", None) is not None and resource in {"competitions", "kernels", "models"}:
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
    return parse_csv_output(result.stdout)


def add_common_output_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a table.")


def command_doctor(args: argparse.Namespace) -> int:
    summary = auth_summary()
    if args.json:
        print_json(summary)
        return 0

    rows = [{"check": key, "value": value} for key, value in summary.items()]
    print_table(rows)
    print()
    if summary["detected_auth_mode"] == "access_token":
        print("Recommendation: keep using KAGGLE_API_TOKEN. It is already detected by kagglehub.")
    elif summary["detected_auth_mode"] == "username_key":
        print("Recommendation: current setup uses legacy username/key credentials.")
    else:
        print("Recommendation: no Kaggle credentials detected. Configure them before downloading.")
    return 0


def command_search(args: argparse.Namespace) -> int:
    rows = search_rows(args)
    if args.json:
        print_json(rows)
    else:
        print_table(rows)
    return 0


def list_files(resource: str, handle: str, *, page_size: int | None = None, page_token: str | None = None) -> list[dict[str, str]]:
    if resource == "datasets":
        command = ["datasets", "files", handle, "--csv"]
    elif resource == "competitions":
        command = ["competitions", "files", handle, "--csv"]
    elif resource == "kernels":
        command = ["kernels", "files", handle, "--csv"]
    elif resource == "models":
        command = ["models", "instances", "versions", "files", handle, "--csv"]
    else:
        raise KgtoolError(f"Files listing is not supported for {resource}")

    if page_size is not None and resource in {"competitions", "models"}:
        command += ["--page-size", str(page_size)]
    if page_token and resource in {"competitions", "models"}:
        command += ["--page-token", page_token]

    return parse_csv_output(run_kaggle(command).stdout)


def load_json_file(directory: Path, pattern: str) -> dict[str, Any]:
    matches = list(directory.glob(pattern))
    if not matches:
        raise KgtoolError(f"Expected metadata file matching {pattern} was not created.")
    with matches[0].open() as fh:
        return json.load(fh)


def dataset_info(handle: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="kgtool-dataset-") as tmpdir:
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
    with tempfile.TemporaryDirectory(prefix="kgtool-model-") as tmpdir:
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
            raise KgtoolError(
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
    if resource == "datasets":
        payload = dataset_info(args.handle)
    elif resource == "competitions":
        payload = competition_info(args.handle)
    elif resource == "kernels":
        payload = kernel_info(args.handle)
    elif resource == "models":
        payload = model_info(args.handle)
    else:
        raise KgtoolError(f"Unsupported resource: {resource}")

    if args.json:
        print_json(payload)
    else:
        print_json(payload)
    return 0


def command_files(args: argparse.Namespace) -> int:
    resource = normalize_resource(args.resource)
    rows = list_files(resource, args.handle, page_size=args.page_size, page_token=args.page_token)
    if args.json:
        print_json(rows)
    else:
        print_table(rows)
    return 0


def command_download(args: argparse.Namespace) -> int:
    output_dir = str(Path(args.output_dir).expanduser().resolve()) if args.output_dir else None
    downloaded_path: str

    if args.resource == "dataset":
        downloaded_path = kagglehub.dataset_download(
            args.handle,
            path=args.path,
            force_download=args.force,
            output_dir=output_dir,
        )
    elif args.resource == "competition":
        downloaded_path = kagglehub.competition_download(
            args.handle,
            path=args.path,
            force_download=args.force,
            output_dir=output_dir,
        )
    elif args.resource == "model":
        downloaded_path = kagglehub.model_download(
            args.handle,
            path=args.path,
            force_download=args.force,
            output_dir=output_dir,
        )
    elif args.resource == "notebook-output":
        downloaded_path = kagglehub.notebook_output_download(
            args.handle,
            path=args.path,
            force_download=args.force,
            output_dir=output_dir,
        )
    else:
        raise KgtoolError(f"Unsupported download resource: {args.resource}")

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


def command_pull_notebook(args: argparse.Namespace) -> int:
    command = ["kernels", "pull", args.handle]
    if args.output_dir:
        command += ["--path", str(Path(args.output_dir).expanduser().resolve())]
    result = run_kaggle(command)
    output = (result.stdout or result.stderr).strip()
    if args.json:
        print_json({"resource": "notebook-code", "handle": args.handle, "result": output})
    else:
        print(output)
    return 0


def command_submit(args: argparse.Namespace) -> int:
    if not args.file and not args.kernel:
        raise KgtoolError("Provide either --file or --kernel for a competition submission.")
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
        payload = {"competition": args.competition, "output_dir": args.output_dir or os.getcwd(), "result": output}
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
    except KgtoolError as exc:
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
                    "Create a submission, then rerun `kgtool submissions`.",
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
        kagglehub.dataset_upload(
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
        command = ["datasets", "version" if args.version else "create", "--path", local_dir]
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
        kagglehub.model_upload(
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
        target_file = target_dir / "kgtool.bash"
        rc_file = Path.home() / ".bashrc"
        source_line = f'source "{target_file}"'
        refresh_cmd = f'source "{target_file}"'
    else:
        target_file = target_dir / "_kgtool"
        rc_file = Path.home() / ".zshrc"
        source_line = f"fpath=({target_dir} $fpath)"
        refresh_cmd = f'fpath=("{target_dir}" $fpath); autoload -Uz compinit && compinit'

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
        print("To make it persistent, add this to your shell config if it is not already there:")
        print(f'  echo \'source "{target_file}"\' >> "{rc_file}"')
    else:
        print("To enable it now, run:")
        print(f'  fpath=("{target_dir}" $fpath)')
        print("  autoload -Uz compinit && compinit")
        print()
        print("To make it persistent, add these lines to your shell config if they are not already there:")
        print(f'  echo \'fpath=("{target_dir}" $fpath)\' >> "{rc_file}"')
        print(f'  echo \'autoload -Uz compinit && compinit\' >> "{rc_file}"')
    print()
    print("Run `kgtool completions` again after reinstalling if you want to refresh the generated completion file.")
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
    raise KgtoolError(f"Could not infer handle from search result: {row}")


def normalize_handle(resource: str, value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("https://www.kaggle.com/"):
        parts = cleaned.removeprefix("https://www.kaggle.com/").split("/")
        if resource == "competitions" and len(parts) >= 2 and parts[0] == "competitions":
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
    return argparse.Namespace(resource=mapped, handle=handle, page_size=None, page_token=None, json=False)


def command_browse(args: argparse.Namespace) -> int:
    print("Interactive browse mode")
    print("Step 1: choose a resource from the menu below using a number or text, or type a search query directly.")
    print("If you type a normal query like `llm` or `gemma`, kgtool will use `datasets` as the default resource.")
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
        print("Try: kgtool browse --resource datasets --search titanic")
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
        raise KgtoolError("Browse choice must be a number.") from exc
    if choice < 1 or choice > len(indexed_rows):
        raise KgtoolError("Browse choice is out of range.")

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
        mapped = {"datasets": "dataset", "competitions": "competition", "models": "model"}[resource]
        destination = download_target_dir(resource, handle, choose_download_destination(resource))
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
        destination = download_target_dir(resource, handle, choose_download_destination(resource))
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
        destination = download_target_dir(resource, handle, choose_download_destination(resource))
        return command_pull_notebook(argparse.Namespace(handle=handle, output_dir=destination, json=False))

    raise KgtoolError(f"Unsupported browse action: {action}")


def build_parser() -> argparse.ArgumentParser:
    parser = KgtoolArgumentParser(
        prog=APP_NAME,
        description="Unified Kaggle helper for search, metadata, files, downloads, and notebook pulls.",
        epilog=textwrap.dedent(USAGE_TEXT),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=KgtoolArgumentParser)

    usage_parser = subparsers.add_parser("usage", help="Show example workflows and common command patterns.")
    usage_parser.set_defaults(func=command_usage)

    completions_parser = subparsers.add_parser("completions", help="Install or print shell completion setup.")
    completions_parser.add_argument("--shell", choices=["bash", "zsh"], help="Shell type. Default is auto-detected from $SHELL.")
    completions_parser.add_argument("--print", action="store_true", help="Print the completion script instead of installing it.")
    add_common_output_flags(completions_parser)
    completions_parser.set_defaults(func=command_completions)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Inspect local Kaggle/KaggleHub availability and authentication state.",
    )
    add_common_output_flags(doctor_parser)
    doctor_parser.set_defaults(func=command_doctor)

    search_parser = subparsers.add_parser("search", help="Search Kaggle resources.")
    search_parser.add_argument("resource", choices=["datasets", "competitions", "kernels", "models"])
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
    add_common_output_flags(search_parser)
    search_parser.set_defaults(func=command_search)

    info_parser = subparsers.add_parser("info", help="Show metadata and related information for a resource.")
    info_parser.add_argument("resource", choices=["dataset", "competition", "notebook", "model"])
    info_parser.add_argument("handle")
    add_common_output_flags(info_parser)
    info_parser.set_defaults(func=command_info)

    files_parser = subparsers.add_parser("files", help="List files for a dataset, competition, notebook, or model version.")
    files_parser.add_argument("resource", choices=["dataset", "competition", "notebook", "model"])
    files_parser.add_argument("handle")
    files_parser.add_argument("--page-size", type=int)
    files_parser.add_argument("--page-token")
    add_common_output_flags(files_parser)
    files_parser.set_defaults(func=command_files)

    download_parser = subparsers.add_parser("download", help="Download Kaggle assets using kagglehub.")
    download_parser.add_argument("resource", choices=["dataset", "competition", "model", "notebook-output"])
    download_parser.add_argument("handle")
    download_parser.add_argument("--path", help="Specific file path within the remote resource.")
    download_parser.add_argument("--output-dir", help="Target directory for the downloaded files.")
    download_parser.add_argument("--force", action="store_true", help="Force a fresh download.")
    add_common_output_flags(download_parser)
    download_parser.set_defaults(func=command_download)

    pull_parser = subparsers.add_parser("pull-notebook", help="Pull notebook source files via the Kaggle CLI.")
    pull_parser.add_argument("handle")
    pull_parser.add_argument("--output-dir")
    add_common_output_flags(pull_parser)
    pull_parser.set_defaults(func=command_pull_notebook)

    submit_parser = subparsers.add_parser("submit", help="Submit a file or notebook run to a Kaggle competition.")
    submit_parser.add_argument("competition")
    submit_parser.add_argument("--file", help="Submission file path.")
    submit_parser.add_argument("--kernel", help="Notebook handle for code competitions.")
    submit_parser.add_argument("--version", type=int, help="Notebook version for code competitions.")
    submit_parser.add_argument("--message", required=True, help="Submission message.")
    add_common_output_flags(submit_parser)
    submit_parser.set_defaults(func=command_submit)

    leaderboard_parser = subparsers.add_parser("leaderboard", help="Show or download a competition leaderboard.")
    leaderboard_parser.add_argument("competition")
    leaderboard_parser.add_argument("--show", action="store_true", help="Show leaderboard rows in the terminal.")
    leaderboard_parser.add_argument("--download", action="store_true", help="Download the leaderboard file.")
    leaderboard_parser.add_argument("--output-dir")
    leaderboard_parser.add_argument("--page-size", type=int)
    leaderboard_parser.add_argument("--page-token")
    add_common_output_flags(leaderboard_parser)
    leaderboard_parser.set_defaults(func=command_leaderboard)

    submissions_parser = subparsers.add_parser("submissions", help="List your submissions for a competition.")
    submissions_parser.add_argument("competition")
    add_common_output_flags(submissions_parser)
    submissions_parser.set_defaults(func=command_submissions)

    upload_dataset_parser = subparsers.add_parser(
        "upload-dataset",
        help="Upload or version a dataset. Use --handle for kagglehub upload, or rely on metadata files for kaggle CLI mode.",
    )
    upload_dataset_parser.add_argument("local_dir")
    upload_dataset_parser.add_argument("--handle", help="Dataset handle for kagglehub upload, e.g. owner/dataset.")
    upload_dataset_parser.add_argument("--message", help="Version notes or create message.")
    upload_dataset_parser.add_argument("--ignore", nargs="*", help="Ignore patterns for kagglehub upload.")
    upload_dataset_parser.add_argument("--version", action="store_true", help="Use `kaggle datasets version` in CLI mode.")
    upload_dataset_parser.add_argument("--public", action="store_true", help="Create the dataset as public in CLI mode.")
    upload_dataset_parser.add_argument("--keep-tabular", action="store_true", help="Keep tabular files in native format in CLI mode.")
    upload_dataset_parser.add_argument("--dir-mode", choices=["skip", "zip", "tar"])
    upload_dataset_parser.add_argument("--delete-old-versions", action="store_true")
    add_common_output_flags(upload_dataset_parser)
    upload_dataset_parser.set_defaults(func=command_upload_dataset)

    upload_model_parser = subparsers.add_parser(
        "upload-model",
        help="Upload a model variation/version. Use --handle for kagglehub upload, or CLI metadata mode for create/update.",
    )
    upload_model_parser.add_argument("local_dir")
    upload_model_parser.add_argument("--handle", help="Model variation handle for kagglehub upload, e.g. owner/model/framework/variation.")
    upload_model_parser.add_argument("--message", help="Version notes for kagglehub upload.")
    upload_model_parser.add_argument("--license-name", help="License name for kagglehub upload when creating a model.")
    upload_model_parser.add_argument("--ignore", nargs="*", help="Ignore patterns for kagglehub upload.")
    upload_model_parser.add_argument("--sigstore", action="store_true", help="Enable sigstore signing in kagglehub mode.")
    upload_model_parser.add_argument("--action", choices=["create", "update"], default="create", help="CLI metadata mode action.")
    add_common_output_flags(upload_model_parser)
    upload_model_parser.set_defaults(func=command_upload_model)

    browse_parser = subparsers.add_parser("browse", help="Interactive terminal workflow for search -> inspect -> download.")
    browse_parser.add_argument("--resource", choices=["datasets", "competitions", "kernels", "models"])
    browse_parser.add_argument("--search")
    browse_parser.add_argument("--sort-by")
    browse_parser.add_argument("--page", type=int, default=1)
    browse_parser.add_argument("--page-size", type=int, default=20)
    browse_parser.add_argument("--limit", type=int, default=10, help="How many search hits to show in the interactive picker.")
    browse_parser.add_argument("--output-dir", help="Default destination for interactive downloads or notebook pulls.")
    browse_parser.set_defaults(func=command_browse)

    return parser


def main(argv: list[str] | None = None) -> int:
    effective_argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    if not effective_argv:
        parser.print_help()
        print()
        print_usage_guide()
        return 0
    args = parser.parse_args(effective_argv)
    try:
        return args.func(args)
    except KgtoolError as exc:
        print(f"{APP_NAME}: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"{APP_NAME}: unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
