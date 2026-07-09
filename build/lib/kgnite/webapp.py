from __future__ import annotations

import base64
import json
import os
import secrets
import shlex
import subprocess
import sys
import threading
import time
import tempfile
import webbrowser
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from kgnite.settings import load_settings


ALLOWED_COMMANDS = {
    "usage",
    "completions",
    "doctor",
    "settings",
    "create-project",
    "workspace-help",
    "search",
    "setup",
    "template",
    "performance",
    "preview",
    "trending",
    "info",
    "files",
    "download",
    "pull-notebook",
    "prepare-notebook",
    "push-notebook",
    "submit",
    "leaderboard",
    "submissions",
    "upload-dataset",
    "upload-model",
}
MAX_BODY_BYTES = 64 * 1024
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024


@dataclass
class WebSession:
    token: str
    cwd: Path
    heartbeat_timeout: float
    command_timeout: float
    connected: bool = False
    upload_dir: Path | None = None
    last_heartbeat: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def heartbeat(self) -> None:
        with self.lock:
            self.connected = True
            self.last_heartbeat = time.monotonic()

    def expired(self) -> bool:
        with self.lock:
            return (
                self.connected
                and time.monotonic() - self.last_heartbeat > self.heartbeat_timeout
            )


def save_uploaded_file(payload: dict[str, Any], session: WebSession) -> Path:
    if session.upload_dir is None:
        raise ValueError("File uploads are not available in this web session.")
    filename = Path(str(payload.get("name", ""))).name
    encoded = payload.get("content")
    if not filename or filename in {".", ".."}:
        raise ValueError("Select a valid submission file.")
    if not isinstance(encoded, str):
        raise ValueError("The uploaded file content is invalid.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("The uploaded file content is invalid.") from exc
    if not content:
        raise ValueError("The selected submission file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("The selected file exceeds the 100 MB upload limit.")
    destination = session.upload_dir / f"{secrets.token_hex(8)}-{filename}"
    destination.write_bytes(content)
    return destination


def parse_command(command: str) -> list[str]:
    try:
        arguments = shlex.split(command)
    except ValueError as exc:
        raise ValueError(f"Could not parse command: {exc}") from exc
    if arguments and arguments[0] == "kgnite":
        arguments = arguments[1:]
    if not arguments:
        raise ValueError("Enter a kgnite command.")
    if arguments[0] not in ALLOWED_COMMANDS:
        allowed = ", ".join(sorted(ALLOWED_COMMANDS))
        raise ValueError(
            f"Unsupported web command `{arguments[0]}`. Allowed commands: {allowed}"
        )
    return arguments


def run_command(arguments: list[str], session: WebSession) -> dict[str, Any]:
    if not arguments or arguments[0] not in ALLOWED_COMMANDS:
        received = arguments[0] if arguments else "empty command"
        raise ValueError(
            f"The requested command is not available in the web session (received: {received})."
        )
    if arguments[0] == "completions" and "--print" not in arguments:
        raise ValueError(
            "Web completion access requires --print and will not modify shell files."
        )
    try:
        environment = os.environ.copy()
        source_root = str(Path(__file__).resolve().parents[1])
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            source_root + os.pathsep + existing_pythonpath
            if existing_pythonpath
            else source_root
        )
        result = subprocess.run(
            [sys.executable, "-m", "kgnite", *arguments],
            cwd=session.cwd,
            env=environment,
            capture_output=True,
            text=True,
            timeout=session.command_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"Command exceeded the {session.command_timeout:g} second timeout."
        ) from exc
    stdout = result.stdout[-MAX_OUTPUT_BYTES:]
    stderr = result.stderr[-MAX_OUTPUT_BYTES:]
    parsed: Any = None
    if stdout.strip():
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            parsed = None
    return {
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "command": ["kgnite", *arguments],
        "stdout": stdout,
        "stderr": stderr,
        "data": parsed,
    }


def page_html(token: str, cwd: Path) -> str:
    config = json.dumps({"token": token, "cwd": str(cwd), "settings": load_settings()})
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>kgnite workstation</title>
  <style>
    :root {{ color-scheme: dark; --bg:#0b1020; --panel:#131b31; --line:#263352; --text:#edf2ff; --muted:#9faccc; --accent:#66e3b4; --accent2:#7ca5ff; --danger:#ff7d8b; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; font:15px/1.45 ui-sans-serif,system-ui,sans-serif; background:linear-gradient(135deg,#0b1020,#111a31 55%,#10243a); color:var(--text); min-height:100vh; }}
    header {{ position:sticky; top:0; z-index:2; backdrop-filter:blur(14px); background:#0b1020dd; border-bottom:1px solid var(--line); padding:16px max(20px,calc((100vw - 1200px)/2)); display:flex; align-items:center; justify-content:space-between; gap:20px; }}
    .brand {{ font-size:21px; font-weight:760; letter-spacing:.02em; }} .brand span {{ color:var(--accent); }} .header-actions {{ display:flex; align-items:center; gap:14px; }} .guide-link {{ color:var(--accent); text-decoration:none; font-weight:700; border:1px solid var(--line); border-radius:9px; padding:8px 11px; }} .guide-link:hover {{ border-color:var(--accent); }} .status {{ color:var(--muted); font-size:13px; }} .dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; background:var(--accent); margin-right:6px; box-shadow:0 0 12px var(--accent); }}
    main {{ max-width:1200px; margin:auto; padding:32px 20px 70px; }} .hero {{ display:grid; grid-template-columns:1.35fr .65fr; gap:18px; margin-bottom:22px; }}
    .card {{ background:#131b31e8; border:1px solid var(--line); border-radius:16px; padding:20px; box-shadow:0 18px 50px #02061455; }} h1 {{ font-size:34px; margin:0 0 8px; }} h2 {{ font-size:18px; margin:0 0 14px; }} p {{ color:var(--muted); margin:5px 0; }}
    nav {{ display:flex; gap:8px; flex-wrap:wrap; margin:0 0 18px; }} button,.button {{ border:1px solid var(--line); background:#1b2743; color:var(--text); border-radius:9px; padding:10px 14px; cursor:pointer; font-weight:650; }} button:hover {{ border-color:var(--accent2); transform:translateY(-1px); }} button.primary {{ background:var(--accent); color:#062119; border-color:transparent; }} button.danger {{ color:var(--danger); }}
    .tab {{ display:none; }} .tab.active {{ display:block; }} .grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; }} form {{ display:grid; gap:11px; }} .row {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }} label {{ color:var(--muted); font-size:13px; display:grid; gap:5px; }} input,select,textarea {{ width:100%; color:var(--text); background:#0c1427; border:1px solid var(--line); border-radius:8px; padding:10px 11px; font:inherit; }} textarea {{ min-height:88px; resize:vertical; }} input[type=checkbox] {{ width:auto; margin-right:7px; }} .check {{ display:flex; align-items:center; }} details {{ border:1px solid var(--line); border-radius:9px; padding:10px; }} summary {{ cursor:pointer; color:var(--accent2); font-weight:650; }} details .row:first-of-type {{ margin-top:10px; }}
    #resultWrap {{ margin-top:20px; }} pre {{ margin:0; min-height:130px; max-height:520px; overflow:auto; white-space:pre-wrap; word-break:break-word; background:#07101f; border:1px solid var(--line); border-radius:10px; padding:15px; color:#dce7ff; }} .result-head {{ display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:9px; }} .result-tools {{ display:flex; align-items:center; gap:7px; }} .view-toggle {{ padding:6px 10px; font-size:12px; }} .view-toggle.active {{ color:#062119; background:var(--accent); border-color:transparent; }} .scroll-hint {{ color:var(--muted); font-size:12px; margin:0 0 7px; }} .table-wrap {{ width:100%; max-height:520px; overflow-x:auto; overflow-y:auto; overscroll-behavior:contain; scrollbar-gutter:stable; border:1px solid var(--line); border-radius:10px; background:#07101f; }} .table-wrap:focus {{ outline:2px solid var(--accent2); outline-offset:2px; }} table {{ width:max-content; min-width:100%; border-collapse:collapse; font-size:13px; table-layout:auto; }} th,td {{ min-width:150px; max-width:360px; padding:10px 12px; text-align:left; vertical-align:top; border-bottom:1px solid var(--line); }} th {{ position:sticky; top:0; z-index:1; white-space:nowrap; background:#17223c; color:var(--accent); }} td {{ white-space:normal; overflow-wrap:break-word; word-break:normal; }} tr:last-child td {{ border-bottom:0; }} tr:hover td {{ background:#101b31; }} .empty {{ color:var(--muted); padding:30px; text-align:center; }} .busy {{ color:var(--accent2); }} .error {{ color:var(--danger); }} code {{ color:var(--accent); }}
    @media(max-width:760px) {{ .hero,.grid,.row {{ grid-template-columns:1fr; }} h1 {{ font-size:28px; }} header {{ align-items:flex-start; }} }}
  </style>
</head>
<body>
<header><div class="brand">kg<span>nite</span> workstation</div><div class="header-actions"><a class="guide-link" href="/guide" target="_blank">Web guide &amp; examples</a><div class="status"><span class="dot"></span>Local session · <span id="cwd"></span></div></div></header>
<main>
  <section class="hero">
    <div class="card"><h1>Kaggle work, from your browser.</h1><p>Discover resources, prepare competitions, generate notebooks, submit work, and track scores. Commands run locally with your existing Kaggle credentials.</p></div>
    <div class="card"><h2>Session lifecycle</h2><p>This server listens on localhost only. Close this page to end the session automatically, or press <code>Ctrl+C</code> in the terminal.</p></div>
  </section>
  <nav>
    <button data-tab="discover" class="primary">Discover</button><button data-tab="competition">Competition</button><button data-tab="projects">Projects</button><button data-tab="resources">Resources</button><button data-tab="uploads">Uploads</button><button data-tab="settings">Settings</button><button data-tab="system">System</button><button data-tab="advanced">Advanced</button>
  </nav>

  <section id="discover" class="tab active"><div class="grid">
    <div class="card"><h2>Search Kaggle</h2><form data-action="search">
      <div class="row"><label>Resource<select name="resource"><option>datasets</option><option>competitions</option><option>kernels</option><option>models</option></select></label><label>Query<input name="query" placeholder="vision transformer"></label></div>
      <div class="row"><label>Sort by<input name="sort" placeholder="votes, hotness, updated…"></label><label>Tags<input name="tags" placeholder="tabular, csv"></label></div><label>Keywords<input name="keywords" placeholder="regression, employee"></label>
      <details><summary>Resource-specific filters and pagination</summary>
        <div class="row"><label>Page<input name="page" type="number" min="1"></label><label>Page size<input name="pageSize" type="number" min="1"></label></div>
        <div class="row"><label>Owner (models)<input name="owner"></label><label>User (datasets/kernels)<input name="user"></label></div>
        <div class="row"><label>Category (competitions)<input name="category"></label><label>Group (competitions)<input name="group"></label></div>
        <div class="row"><label>Language (kernels)<input name="language"></label><label>Kernel type<input name="kernelType" placeholder="notebook or script"></label></div>
        <div class="row"><label>Output type (kernels)<input name="outputType"></label><label>Dataset handle (kernels)<input name="dataset"></label></div>
        <label>Competition slug (kernels)<input name="competition"></label>
      </details>
      <button class="primary">Search</button></form></div>
    <div class="card"><h2>Trending resources</h2><form data-action="trending">
      <div class="row"><label>Resource<select name="resource"><option>datasets</option><option>competitions</option><option>kernels</option><option>models</option></select></label><label>Order<select name="order"><option>popular</option><option>new</option></select></label></div>
      <div class="row"><label>Search<input name="query" placeholder="optional"></label><label>Limit<input name="limit" type="number" min="1" value="10"></label></div>
      <div class="row"><label>Tags<input name="tags" placeholder="python, notebook"></label><label>Keywords<input name="keywords" placeholder="pytorch, transformer"></label></div><label>Category (competitions)<input name="category"></label>
      <button class="primary">Show resources</button></form></div>
  </div></section>

  <section id="projects" class="tab"><div class="grid">
    <div class="card"><h2>Create project</h2><p>Create a generic Kaggle-ready project under the configured projects directory.</p><form data-action="createProject">
      <label>Project name<input name="name" required placeholder="customer-churn"></label><label>Directory (optional)<input name="directory" placeholder="Uses Settings → Workspace/projects"></label><label>Participant<input name="participant"></label><label>Kaggle dataset sources<input name="datasets" placeholder="owner/dataset-one, owner/dataset-two"></label><label>Kaggle notebook sources<input name="kernels" placeholder="owner/notebook"></label><label>Kaggle model sources<input name="models" placeholder="owner/model/framework/variation"></label><div class="row"><label class="check"><span><input type="checkbox" name="template" checked>Generate notebook</span></label><label class="check"><span><input type="checkbox" name="force">Replace generated files</span></label></div><button class="primary">Create project</button></form></div>
  </div></section>

  <section id="competition" class="tab"><div class="grid">
    <div class="card"><h2>Set up competition</h2><form data-action="setup">
      <label>Competition slug<input name="competition" required placeholder="titanic"></label><div class="row"><label>Workspace directory<input name="directory" placeholder="Uses Settings → Workspace/competitions"></label><label>Participant name<input name="participant" placeholder="Your name"></label></div>
      <div class="row"><label>Metric<input name="metric" value="publicScore"></label><label class="check"><span><input type="checkbox" name="lower">Lower score is better</span></label></div>
      <div class="row"><label class="check"><span><input type="checkbox" name="download" checked>Download competition data</span></label><label class="check"><span><input type="checkbox" name="template" checked>Generate notebook</span></label></div><div class="row"><label class="check"><span><input type="checkbox" name="notes" checked>Include official competition notes</span></label><label>Notes pages, comma separated<input name="notesPages" value="data-description" placeholder="data-description, evaluation"></label></div>
      <label class="check"><span><input type="checkbox" name="force">Replace an existing generated workspace</span></label>
      <button class="primary">Create workspace</button></form></div>
    <div class="card"><h2>Generate notebook</h2><form data-action="template">
      <label>Competition slug<input name="competition" required placeholder="titanic"></label><div class="row"><label>Participant name<input name="participant" placeholder="Your name"></label><label>Data directory<input name="data" value="./data"></label></div><label>Output notebook<input name="output" placeholder="Auto: titanic-01.ipynb, titanic-02.ipynb, ..."></label><div class="row"><label class="check"><span><input type="checkbox" name="notes" checked>Include official competition notes</span></label><label>Notes pages<input name="notesPages" value="data-description"></label></div><label class="check"><span><input type="checkbox" name="force">Replace existing notebook</span></label>
      <button class="primary">Generate notebook</button></form></div>
    <div class="card"><h2>Performance history</h2><form data-action="performance">
      <label>Competition slug<input name="competition" required placeholder="titanic"></label><label>History file<input name="history" placeholder=".kgnite/titanic-scores.json"></label>
      <div class="row"><label class="check"><span><input type="checkbox" name="sync" checked>Sync from Kaggle</span></label><label class="check"><span><input type="checkbox" name="lower">Lower score is better</span></label></div>
      <button class="primary">Track performance</button></form></div>
    <div class="card"><h2>Submit result</h2><form data-action="submit">
      <label>Competition slug<input name="competition" required placeholder="titanic"></label><label>Submission file path<input name="filePath" placeholder="/path/to/submission.csv"></label><label>Or browse for a submission file (optional)<input name="filePicker" type="file" accept=".csv,.zip"></label><div class="row"><label>Notebook handle (code competitions)<input name="kernel" placeholder="owner/notebook"></label><label>Notebook version<input name="version" type="number" min="1"></label></div><label>Message<input name="message" required placeholder="Random Forest prediction"></label>
      <button class="primary">Submit to Kaggle</button></form></div>
  </div></section>

  <section id="resources" class="tab"><div class="grid">
    <div class="card"><h2>Inspect or list files</h2><p>Search first, then copy the result's <code>ref</code>. A dataset handle looks like <code>owner/dataset-slug</code>; it is not a search query.</p><form data-action="inspect">
      <div class="row"><label>Action<select name="action"><option value="info">Resource info</option><option value="files">List files</option></select></label><label>Type<select name="resource"><option>dataset</option><option>competition</option><option>notebook</option><option>model</option></select></label></div>
      <label>Resource handle<input name="handle" required placeholder="tawfikelmetwally/employee-dataset"></label><div class="row"><label>Page size (files)<input name="pageSize" type="number" min="1"></label><label>Page token (files)<input name="pageToken"></label></div><button class="primary">Run</button></form></div>
    <div class="card"><h2>Download</h2><form data-action="download">
      <label>Type<select name="resource"><option>dataset</option><option>competition</option><option>model</option><option>notebook-output</option></select></label><label>Resource handle<input name="handle" required placeholder="owner/resource-slug"></label><div class="row"><label>Remote file path<input name="path"></label><label>Output directory<input name="output" placeholder="./downloads"></label></div><label class="check"><span><input type="checkbox" name="force">Force fresh download</span></label>
      <button class="primary">Download</button></form></div>
    <div class="card"><h2>Preview data</h2><p>Inspect shape, column names, and sample rows from a Kaggle dataset, absolute workstation path, or HTTP/HTTPS URL.</p><form data-action="preview">
      <label>Source type<select name="sourceType"><option value="dataset">Kaggle dataset</option><option value="local">Absolute local path</option><option value="url">Remote URL</option></select></label><label>Source<input name="source" required placeholder="tawfikelmetwally/employee-dataset"></label><label>Kaggle file path (optional)<input name="path" placeholder="Employee.csv"></label><div class="row"><label>Rows<input name="rows" type="number" min="1" value="10"></label><label>Columns (number or all)<input name="columns" value="10" placeholder="all"></label></div><div class="row"><label>Maximum file size (MB)<input name="maxSize" type="number" min="0.1" step="0.1" value="25"></label><label class="check"><span><input type="checkbox" name="force">Refresh cached Kaggle file</span></label></div><button class="primary">Preview data</button></form></div>
    <div class="card"><h2>My submissions</h2><form data-action="submissions"><label>Competition slug<input name="competition" required></label><button class="primary">List submissions</button></form></div>
    <div class="card"><h2>Leaderboard</h2><form data-action="leaderboard"><label>Competition slug<input name="competition" required></label><div class="row"><label>Page size<input name="pageSize" type="number" min="1"></label><label>Page token<input name="pageToken"></label></div><label>Download directory (optional)<input name="output"></label><button class="primary">Show or download leaderboard</button></form></div>
    <div class="card"><h2>Pull notebook source</h2><form data-action="pull"><label>Notebook handle<input name="handle" required placeholder="owner/notebook"></label><label>Output directory<input name="output" placeholder="./notebooks"></label><button class="primary">Pull source</button></form></div>
  </div></section>

  <section id="uploads" class="tab"><div class="grid">
    <div class="card"><h2>Prepare Kaggle notebook</h2><p>Create a project-local upload bundle without publishing it. The Kaggle slug is derived from the title.</p><form data-action="prepareNotebook">
      <label>Notebook path<input name="notebook" required placeholder="./titanic/notebooks/titanic-01.ipynb"></label><label>Notebook title<input name="title" placeholder="Titanic Random Forest"></label><div class="row"><label>Kaggle handle owner/slug (optional)<input name="handle" placeholder="rajinh/titanic-random-forest"></label><label>Competition slug (optional)<input name="competition" placeholder="titanic"></label></div><label>Bundle directory (optional)<input name="output" placeholder="Auto: project/kaggle-notebooks/title-slug"></label><label>Dataset sources<input name="datasets" placeholder="owner/dataset, owner/another"></label><label>Competition sources<input name="competitions" placeholder="titanic"></label><label>Notebook sources<input name="kernels" placeholder="owner/notebook"></label><label>Model sources<input name="models" placeholder="owner/model/framework/variation"></label><details><summary>Stage a local dataset</summary><label>Local dataset directory<input name="localDataset"></label><label>Kaggle dataset handle<input name="datasetHandle" placeholder="rajinh/project-data"></label><div class="row"><label>Dataset title<input name="datasetTitle"></label><label>Dataset license<input name="datasetLicense" placeholder="Uses configured default"></label></div></details><div class="row"><label class="check"><span><input type="checkbox" name="public">Public notebook</span></label><label class="check"><span><input type="checkbox" name="force">Replace prepared bundles</span></label></div><button class="primary">Prepare notebook</button></form></div>
    <div class="card"><h2>Push Kaggle notebook</h2><p>Create or update a previously prepared notebook in your Kaggle profile.</p><form data-action="pushNotebook">
      <label>Bundle directory<input name="directory" required placeholder="./titanic/kaggle-notebooks/titanic-rf"></label><div class="row"><label>Timeout in seconds<input name="timeout" type="number" min="1"></label><label>Accelerator<input name="accelerator" placeholder="optional"></label></div><div class="row"><label class="check"><span><input type="checkbox" name="withDatasets">Push staged local datasets first</span></label><label>Dataset action<select name="datasetAction"><option>create</option><option>version</option></select></label></div><label class="check"><span><input type="checkbox" name="publicDatasets" checked>Make newly created datasets public</span></label><button class="primary">Push to Kaggle</button></form></div>
    <div class="card"><h2>Upload dataset</h2><p>Provide a handle for direct KaggleHub mode, or leave it empty for metadata-folder CLI mode.</p><form data-action="uploadDataset">
      <label>Local directory<input name="directory" required placeholder="./my-dataset"></label><label>Dataset handle (optional)<input name="handle" placeholder="owner/dataset"></label><label>Message<input name="message"></label><label>Ignore patterns, comma separated<input name="ignore"></label>
      <div class="row"><label class="check"><span><input type="checkbox" name="version">Create a new version</span></label><label class="check"><span><input type="checkbox" name="public">Public dataset</span></label></div>
      <div class="row"><label>Directory mode<select name="dirMode"><option value="">Default</option><option>skip</option><option>zip</option><option>tar</option></select></label><label class="check"><span><input type="checkbox" name="keep">Keep tabular files</span></label></div>
      <label class="check"><span><input type="checkbox" name="deleteOld">Delete old versions</span></label><button class="primary">Upload dataset</button></form></div>
    <div class="card"><h2>Upload model</h2><p>Provide a handle for KaggleHub mode, or use create/update metadata mode.</p><form data-action="uploadModel">
      <label>Local directory<input name="directory" required placeholder="./my-model"></label><label>Model handle (optional)<input name="handle" placeholder="owner/model/framework/variation"></label><div class="row"><label>Message<input name="message"></label><label>License<input name="license"></label></div><label>Ignore patterns, comma separated<input name="ignore"></label>
      <div class="row"><label>Metadata action<select name="modelAction"><option>create</option><option>update</option></select></label><label class="check"><span><input type="checkbox" name="sigstore">Enable Sigstore</span></label></div><button class="primary">Upload model</button></form></div>
  </div></section>

  <section id="settings" class="tab"><div class="grid">
    <div class="card"><h2>Workspace settings</h2><p>Stored in <code id="settingsFile"></code>.</p><form data-action="settings">
      <label>Workspace directory<input name="workspace" required></label><div class="row"><label>Competitions folder<input name="competitions" required></label><label>Projects folder<input name="projects" required></label></div><label>Kaggle username<input name="username"></label><label>Default dataset license<input name="license" placeholder="CC0-1.0"></label><button class="primary">Save settings</button></form></div>
  </div></section>

  <section id="system" class="tab"><div class="grid">
    <div class="card"><h2>Diagnostics</h2><p>Inspect Kaggle CLI, KaggleHub, credentials, and runtime status.</p><form data-action="doctor"><button class="primary">Run doctor</button></form></div>
    <div class="card"><h2>Usage guide</h2><p>Display the built-in workflow examples.</p><form data-action="usage"><button class="primary">Show usage</button></form></div>
    <div class="card"><h2>Shell completion script</h2><p>Print completion definitions without modifying shell configuration.</p><form data-action="completions"><label>Shell<select name="shell"><option>zsh</option><option>bash</option></select></label><button class="primary">Print completion script</button></form></div>
    <div class="card"><h2>Interactive browse</h2><p>The CLI <code>browse</code> workflow is represented by the Discover and Resources pages. Recursive <code>web</code> launch and terminal-interactive browsing are intentionally not run inside this session.</p></div>
  </div></section>

  <section id="advanced" class="tab"><div class="card"><h2>Advanced command runner</h2><p>Run any non-interactive kgnite command except <code>web</code> and <code>browse</code>. Completion scripts require <code>completions --print</code>. Commands are parsed into arguments and never passed through a shell.</p><form data-action="advanced">
    <label>Command<textarea name="command" placeholder='kgnite search datasets "house prices" --sort-by votes --json'></textarea></label><button class="primary">Run command</button></form></div></section>

  <section id="resultWrap" class="card"><div class="result-head"><h2>Result</h2><div class="result-tools"><button type="button" id="tableView" class="view-toggle active">Table</button><button type="button" id="jsonView" class="view-toggle">JSON</button><span id="resultStatus">Ready</span></div></div><div id="result"><pre>Results will appear here.</pre></div></section>
</main>
<script>
const CONFIG={config}; document.querySelector('#cwd').textContent=CONFIG.cwd; document.querySelector('#settingsFile').textContent=CONFIG.settings.settings_file; const settingsForm=document.querySelector('[data-action=settings]'); settingsForm.elements.workspace.value=CONFIG.settings.workspace_dir; settingsForm.elements.competitions.value=CONFIG.settings.competitions_dir; settingsForm.elements.projects.value=CONFIG.settings.projects_dir; settingsForm.elements.username.value=CONFIG.settings.kaggle_username||''; settingsForm.elements.license.value=CONFIG.settings.default_dataset_license||'';
const result=document.querySelector('#result'), statusEl=document.querySelector('#resultStatus'), tableButton=document.querySelector('#tableView'), jsonButton=document.querySelector('#jsonView');
let lastResponse=null, resultMode='table';
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{{ document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active')); document.querySelector('#'+b.dataset.tab).classList.add('active'); document.querySelectorAll('[data-tab]').forEach(x=>x.classList.remove('primary')); b.classList.add('primary'); }});
function add(args,flag,value){{ if(value!==undefined && value!==null && String(value).trim()!=='') args.push(flag,String(value).trim()); }}
function csv(value){{ return value.split(',').map(x=>x.trim()).filter(Boolean); }}
function build(action,f){{ let a=[]; const e=f.elements;
  if(action==='search'){{ a=['search',e.resource.value]; if(e.query.value)a.push(e.query.value); add(a,'--sort-by',e.sort.value); add(a,'--page',e.page.value); add(a,'--page-size',e.pageSize.value); add(a,'--owner',e.owner.value); add(a,'--user',e.user.value); add(a,'--category',e.category.value); add(a,'--group',e.group.value); add(a,'--language',e.language.value); add(a,'--kernel-type',e.kernelType.value); add(a,'--output-type',e.outputType.value); add(a,'--dataset',e.dataset.value); add(a,'--competition',e.competition.value); csv(e.tags.value).forEach(x=>add(a,'--tag',x)); csv(e.keywords.value).forEach(x=>add(a,'--keyword',x)); a.push('--json'); }}
  if(action==='trending'){{ a=['trending',e.resource.value,'--order',e.order.value,'--limit',e.limit.value]; add(a,'--search',e.query.value); add(a,'--category',e.category.value); csv(e.tags.value).forEach(x=>add(a,'--tag',x)); csv(e.keywords.value).forEach(x=>add(a,'--keyword',x)); a.push('--json'); }}
  if(action==='setup'){{ a=['setup',e.competition.value,'--metric',e.metric.value,e.lower.checked?'--lower-is-better':'--no-lower-is-better',e.download.checked?'--download':'--no-download',e.template.checked?'--template':'--no-template',e.notes.checked?'--competition-notes':'--no-competition-notes']; add(a,'--directory',e.directory.value); add(a,'--participant',e.participant.value); if(e.notes.checked)csv(e.notesPages.value).forEach(x=>add(a,'--notes-page',x)); if(e.force.checked)a.push('--force'); a.push('--json'); }}
  if(action==='createProject'){{ a=['create-project',e.name.value,e.template.checked?'--template':'--no-template']; add(a,'--directory',e.directory.value); add(a,'--participant',e.participant.value); csv(e.datasets.value).forEach(x=>add(a,'--dataset-source',x)); csv(e.kernels.value).forEach(x=>add(a,'--kernel-source',x)); csv(e.models.value).forEach(x=>add(a,'--model-source',x)); if(e.force.checked)a.push('--force'); a.push('--json'); }}
  if(action==='template'){{ a=['template',e.competition.value,'--data-dir',e.data.value,e.notes.checked?'--competition-notes':'--no-competition-notes']; add(a,'--participant',e.participant.value); add(a,'--output',e.output.value); if(e.notes.checked)csv(e.notesPages.value).forEach(x=>add(a,'--notes-page',x)); if(e.force.checked)a.push('--force'); a.push('--json'); }}
  if(action==='performance'){{ a=['performance',e.competition.value]; add(a,'--history',e.history.value); if(e.sync.checked)a.push('--sync'); if(e.lower.checked)a.push('--lower-is-better'); a.push('--json'); }}
  if(action==='submit'){{ a=['submit',e.competition.value]; add(a,'--file',e.filePath.value); add(a,'--kernel',e.kernel.value); add(a,'--version',e.version.value); a.push('--message',e.message.value,'--json'); }}
  if(action==='inspect'){{ a=[e.action.value,e.resource.value,e.handle.value]; if(e.action.value==='files'){{ add(a,'--page-size',e.pageSize.value); add(a,'--page-token',e.pageToken.value); }} a.push('--json'); }}
  if(action==='download'){{ a=['download',e.resource.value,e.handle.value]; add(a,'--path',e.path.value); add(a,'--output-dir',e.output.value); if(e.force.checked)a.push('--force'); a.push('--json'); }}
  if(action==='preview'){{ a=['preview',e.sourceType.value,e.source.value,'--rows',e.rows.value,'--columns',e.columns.value,'--max-file-size-mb',e.maxSize.value]; if(e.sourceType.value==='dataset') add(a,'--path',e.path.value); if(e.force.checked && e.sourceType.value==='dataset')a.push('--force'); a.push('--json'); }}
  if(action==='submissions'){{ a=['submissions',e.competition.value,'--json']; }}
  if(action==='leaderboard'){{ a=['leaderboard',e.competition.value]; if(e.output.value){{ a.push('--download'); add(a,'--output-dir',e.output.value); }}else a.push('--show'); add(a,'--page-size',e.pageSize.value); add(a,'--page-token',e.pageToken.value); a.push('--json'); }}
  if(action==='pull'){{ a=['pull-notebook',e.handle.value]; add(a,'--output-dir',e.output.value); a.push('--json'); }}
  if(action==='prepareNotebook'){{ a=['prepare-notebook',e.notebook.value]; add(a,'--handle',e.handle.value); add(a,'--competition',e.competition.value); add(a,'--title',e.title.value); add(a,'--output-dir',e.output.value); csv(e.datasets.value).forEach(x=>add(a,'--dataset-source',x)); csv(e.competitions.value).forEach(x=>add(a,'--competition-source',x)); csv(e.kernels.value).forEach(x=>add(a,'--kernel-source',x)); csv(e.models.value).forEach(x=>add(a,'--model-source',x)); add(a,'--local-dataset',e.localDataset.value); add(a,'--dataset-handle',e.datasetHandle.value); add(a,'--dataset-title',e.datasetTitle.value); add(a,'--dataset-license',e.datasetLicense.value); if(e.public.checked)a.push('--public'); if(e.force.checked)a.push('--force'); a.push('--json'); }}
  if(action==='pushNotebook'){{ a=['push-notebook',e.directory.value]; add(a,'--timeout',e.timeout.value); add(a,'--accelerator',e.accelerator.value); if(e.withDatasets.checked)a.push('--with-datasets','--dataset-action',e.datasetAction.value,e.publicDatasets.checked?'--public-datasets':'--no-public-datasets'); a.push('--json'); }}
  if(action==='uploadDataset'){{ a=['upload-dataset',e.directory.value]; add(a,'--handle',e.handle.value); add(a,'--message',e.message.value); if(e.version.checked)a.push('--version'); if(e.public.checked)a.push('--public'); if(e.keep.checked)a.push('--keep-tabular'); add(a,'--dir-mode',e.dirMode.value); if(e.deleteOld.checked)a.push('--delete-old-versions'); if(e.ignore.value) a.push('--ignore',...csv(e.ignore.value)); a.push('--json'); }}
  if(action==='uploadModel'){{ a=['upload-model',e.directory.value]; add(a,'--handle',e.handle.value); add(a,'--message',e.message.value); add(a,'--license-name',e.license.value); if(e.sigstore.checked)a.push('--sigstore'); add(a,'--action',e.modelAction.value); if(e.ignore.value) a.push('--ignore',...csv(e.ignore.value)); a.push('--json'); }}
  if(action==='settings'){{ a=['settings','--workspace-dir',e.workspace.value,'--competitions-dir',e.competitions.value,'--projects-dir',e.projects.value]; add(a,'--kaggle-username',e.username.value); add(a,'--default-dataset-license',e.license.value); a.push('--json'); }}
  if(action==='doctor'){{ a=['doctor','--json']; }}
  if(action==='usage'){{ a=['usage']; }}
  if(action==='completions'){{ a=['completions','--shell',e.shell.value,'--print']; }} return a; }}
function scalar(value){{ return value!==null && typeof value==='object'?JSON.stringify(value):String(value??''); }}
function renderTable(rows){{ const wrap=document.createElement('div'); wrap.className='table-wrap'; wrap.tabIndex=0; wrap.setAttribute('role','region'); wrap.setAttribute('aria-label','Scrollable tabular results'); if(rows.length===0){{ const empty=document.createElement('div'); empty.className='empty'; empty.textContent='No results.'; wrap.appendChild(empty); result.replaceChildren(wrap); return; }} const columns=[...new Set(rows.flatMap(row=>row && typeof row==='object' && !Array.isArray(row)?Object.keys(row):['value']))]; const hint=document.createElement('p'); hint.className='scroll-hint'; hint.textContent=`${{columns.length}} columns · Scroll horizontally to view columns beyond the page width.`; const table=document.createElement('table'), head=document.createElement('thead'), headerRow=document.createElement('tr'); columns.forEach(column=>{{ const th=document.createElement('th'); th.textContent=column; th.title=column; headerRow.appendChild(th); }}); head.appendChild(headerRow); table.appendChild(head); const body=document.createElement('tbody'); rows.forEach(row=>{{ const tr=document.createElement('tr'); columns.forEach(column=>{{ const td=document.createElement('td'); td.textContent=scalar(row && typeof row==='object' && !Array.isArray(row)?row[column]:row); tr.appendChild(td); }}); body.appendChild(tr); }}); table.appendChild(body); wrap.appendChild(table); result.replaceChildren(hint,wrap); }}
function renderResult(){{ tableButton.classList.toggle('active',resultMode==='table'); jsonButton.classList.toggle('active',resultMode==='json'); if(!lastResponse) return; const data=lastResponse.data, rows=Array.isArray(data)?data:(data && Array.isArray(data.rows)?data.rows:null); if(resultMode==='table' && rows){{ renderTable(rows); return; }} const pre=document.createElement('pre'); pre.textContent=data!==null&&data!==undefined?JSON.stringify(data,null,2):[lastResponse.stdout,lastResponse.stderr].filter(Boolean).join('\\n')||JSON.stringify(lastResponse,null,2); result.replaceChildren(pre); }}
tableButton.onclick=()=>{{ resultMode='table'; renderResult(); }}; jsonButton.onclick=()=>{{ resultMode='json'; renderResult(); }};
async function execute(payload){{ statusEl.textContent='Running…'; statusEl.className='busy'; const pre=document.createElement('pre'); pre.textContent='Working locally. Kaggle operations may take a moment.'; result.replaceChildren(pre); try {{ const r=await fetch('/api/run',{{method:'POST',headers:{{'Content-Type':'application/json','X-Kgnite-Token':CONFIG.token}},body:JSON.stringify(payload)}}); lastResponse=await r.json(); statusEl.textContent=lastResponse.ok?'Completed':'Failed'; statusEl.className=lastResponse.ok?'':'error'; renderResult(); }} catch(e){{ lastResponse={{ok:false,data:null,stdout:'',stderr:String(e)}}; statusEl.textContent='Error'; statusEl.className='error'; renderResult(); }} result.scrollIntoView({{behavior:'smooth',block:'nearest'}}); }}
async function uploadSelectedFile(f){{ const file=f.elements.filePicker?.files[0]; if(!file)return; if(file.size>100*1024*1024)throw new Error('The selected file exceeds the 100 MB upload limit.'); const content=await new Promise((resolve,reject)=>{{ const reader=new FileReader(); reader.onload=()=>resolve(String(reader.result).split(',',2)[1]); reader.onerror=()=>reject(reader.error); reader.readAsDataURL(file); }}); const r=await fetch('/api/upload',{{method:'POST',headers:{{'Content-Type':'application/json','X-Kgnite-Token':CONFIG.token}},body:JSON.stringify({{name:file.name,content}})}}); const response=await r.json(); if(!r.ok)throw new Error(response.error||'File upload failed.'); f.elements.filePath.value=response.path; }}
document.querySelectorAll('form').forEach(f=>f.onsubmit=async e=>{{ e.preventDefault(); const action=f.getAttribute('data-action'); if(['submit','pushNotebook','uploadDataset','uploadModel'].includes(action) && !window.confirm('This operation changes data on Kaggle. Continue?')) return; try{{ if(action==='submit')await uploadSelectedFile(f); execute(action==='advanced'?{{command:f.elements.command.value}}:{{arguments:build(action,f)}}); }}catch(error){{ lastResponse={{ok:false,data:null,stdout:'',stderr:String(error)}}; statusEl.textContent='Error'; statusEl.className='error'; renderResult(); }} }});
async function beat(){{ try{{ await fetch('/api/heartbeat',{{method:'POST',headers:{{'X-Kgnite-Token':CONFIG.token}}}}); }}catch(_){{}} }} beat(); setInterval(beat,2000);
</script>
</body></html>"""


def guide_html(token: str) -> str:
    safe_token = json.dumps(token)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>kgnite Web Guide</title><style>
:root{{color-scheme:dark;--bg:#0b1020;--panel:#131b31;--line:#263352;--text:#edf2ff;--muted:#aab5d1;--accent:#66e3b4;--accent2:#8badff}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:linear-gradient(135deg,#0b1020,#111a31);color:var(--text);font:16px/1.65 ui-sans-serif,system-ui,sans-serif}}main{{max-width:980px;margin:auto;padding:36px 22px 80px}}header{{border-bottom:1px solid var(--line);background:#0b1020e8;position:sticky;top:0;z-index:2;padding:14px max(22px,calc((100vw - 980px)/2));display:flex;justify-content:space-between;align-items:center}}.brand{{font-size:20px;font-weight:800}}.brand span,a,h2{{color:var(--accent)}}a{{text-decoration:none}}.back{{border:1px solid var(--line);padding:7px 11px;border-radius:8px}}h1{{font-size:40px;line-height:1.15;margin:10px 0}}h2{{font-size:24px;margin-top:45px;border-bottom:1px solid var(--line);padding-bottom:7px}}h3{{color:var(--accent2);margin-top:28px}}p,li{{color:var(--muted)}}.lead{{font-size:19px}}.notice,.card{{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:16px 19px;margin:17px 0}}.toc{{columns:2}}.toc a{{display:block;padding:4px 0}}code{{color:var(--accent);background:#081223;padding:2px 5px;border-radius:4px}}pre{{background:#07101f;border:1px solid var(--line);padding:14px;border-radius:9px;overflow:auto;color:#dce7ff}}table{{width:100%;border-collapse:collapse;background:#0b1427}}th,td{{padding:10px;border:1px solid var(--line);text-align:left;vertical-align:top}}th{{color:var(--accent)}}strong{{color:var(--text)}}@media(max-width:650px){{.toc{{columns:1}}h1{{font-size:32px}}header{{align-items:flex-start;gap:12px}}}}
</style></head><body>
<header><div class="brand">kgnite · Web Guide</div><a class="back" href="/">Back to workstation</a></header>
<main><h1>Use kgnite confidently from your browser</h1><p class="lead">This guide explains every web page, the difference between queries and handles, practical competition workflows, uploads, result views, and common errors.</p>
<div class="notice"><strong>Local by design.</strong> The workstation runs on <code>127.0.0.1</code>, uses your existing Kaggle credentials, and resolves relative paths from the directory shown in the workstation header.</div>
<div class="card toc"><a href="#start">1. Start and authenticate</a><a href="#handles">2. Queries and handles</a><a href="#discover">3. Discover resources</a><a href="#competition">4. Competition workflow</a><a href="#resources">5. Inspect and download</a><a href="#uploads">6. Upload datasets and models</a><a href="#system">7. System and Advanced</a><a href="#results">8. Table and JSON results</a><a href="#troubleshooting">9. Troubleshooting</a><a href="#security">10. Security and shutdown</a></div>

<h2 id="start">1. Start and authenticate</h2><pre>cd ~/kaggle-work
export KAGGLE_API_TOKEN="your_token_here"
kgnite web</pre><p>Open <strong>System → Diagnostics</strong> first. Confirm that the Kaggle CLI, KaggleHub, and credentials are detected. Close the page to end the server after its heartbeat grace period, or press <code>Ctrl+C</code> for immediate shutdown.</p>
<h3>Useful launch options</h3><pre>kgnite web --port 8765
kgnite web --no-browser
kgnite web --heartbeat-timeout 60
kgnite web --command-timeout 900</pre>

<h2 id="handles">2. Queries and handles</h2><p>A <strong>query</strong> is discovery text. A <strong>handle</strong> uniquely identifies a result. Search with a query, then copy the handle from the result table's <code>ref</code> column.</p>
<table><thead><tr><th>Resource</th><th>Query</th><th>Handle</th></tr></thead><tbody><tr><td>Dataset</td><td><code>employee</code></td><td><code>tawfikelmetwally/employee-dataset</code></td></tr><tr><td>Competition</td><td><code>titanic</code></td><td><code>titanic</code></td></tr><tr><td>Notebook</td><td><code>house prices</code></td><td><code>owner/notebook-slug</code></td></tr><tr><td>Model</td><td><code>gemma</code></td><td><code>google/gemma</code></td></tr></tbody></table>
<p>Use queries on <strong>Discover</strong>. Use handles for resource info, files, downloads, notebook pulls, and uploads.</p>

<h2 id="discover">3. Discover resources</h2><h3>Search</h3><ol><li>Select datasets, competitions, kernels, or models.</li><li>Enter a query and optional sort order.</li><li>Add tags and keywords when needed.</li><li>Open resource-specific filters for owner, user, category, language, linked dataset/competition, and pagination.</li><li>Select Search and copy the desired <code>ref</code>.</li></ol>
<div class="card"><strong>Example: employee datasets</strong><pre>Resource: datasets
Query: employee
Sort by: votes
Tags: tabular
Keywords: attrition</pre></div>
<h3>Trending</h3><p>Choose <strong>popular</strong> for activity-ranked resources or <strong>new</strong> for recently created or updated resources.</p><pre>Resource: kernels
Order: new
Search: transformer
Keywords: pytorch
Limit: 20</pre>

<h2 id="competition">4. Competition workflow</h2><h3>Set up a workspace</h3><pre>Competition: titanic
Workspace: ./titanic
Metric: accuracy
Download data: checked
Generate notebook: checked</pre><p>This creates <code>.&lt;competition-slug&gt;-config.json</code>, <code>data/</code>, <code>notebooks/</code>, and <code>submissions/</code>. Enable replacement only when overwriting generated files is intentional.</p>
<h3>Generate a notebook</h3><pre>Competition: titanic
Participant: Your Name
Data directory: ./titanic/data
Output: ./titanic/notebooks/titanic-02.ipynb
Official notes: checked
Notes pages: data-description, evaluation</pre><p>The notebook is presented as the participant's personal workspace. Official page content is fetched through Kaggle's API, linked to its source, sanitized, and embedded for reference.</p>
<h3>Track scores</h3><pre>Competition: titanic
History: ./titanic/scores.json
Sync from Kaggle: checked</pre><p>Enable lower-is-better for loss or error metrics. Disable synchronization to view local history without contacting Kaggle.</p>
<h3>Submit</h3><p>For file competitions, enter a local path or use the optional file picker. Selected files use temporary storage that is removed when the web session ends. For code competitions, provide a notebook handle and version. The browser asks for confirmation before submitting.</p><pre>Competition: titanic
Submission file: ./titanic/submissions/submission.csv
Message: random forest baseline</pre>

<h2 id="resources">5. Inspect, preview, pull, and download</h2><h3>Inspect a dataset</h3><pre>Action: List files
Type: dataset
Handle: tawfikelmetwally/employee-dataset</pre><h3>Preview rows and shape</h3><p>Preview reports total shape, every detected column name, displayed dimensions, and sample rows. Choose a Kaggle dataset, absolute local path, or HTTP/HTTPS URL. Leave the Kaggle file path empty for automatic selection and retain the size guard for large sources.</p><pre>Source type: Kaggle dataset
Source: tawfikelmetwally/employee-dataset
Remote path: Employee.csv
Rows: 20
Columns: all
Maximum file size: 25 MB</pre><h3>Download</h3><pre>Type: dataset
Handle: tawfikelmetwally/employee-dataset
Output directory: ./downloads/employees</pre><p>Provide a remote path to fetch one file. Force refresh bypasses cached data. Notebook source uses <strong>Pull notebook source</strong>; generated notebook files use download type <code>notebook-output</code>.</p><p>Leaderboard displays rows unless you provide a download directory. Submission history requires that you have joined the competition and accepted its rules.</p>

<h2 id="uploads">6. Upload notebooks, datasets, and models</h2><p>Uploads change Kaggle data and require confirmation. Notebook preparation derives the Kaggle slug from the title so the metadata ID matches Kaggle's URL behavior. Add a notebook handle only when choosing a different owner. Dataset and model handles use direct KaggleHub mode; leaving them blank uses Kaggle CLI metadata-folder mode.</p><h3>Dataset example</h3><pre>Local directory: ./my-dataset
Handle: username/my-dataset
Message: initial version
Ignore: .DS_Store, *.tmp</pre><h3>Model example</h3><pre>Local directory: ./my-model
Handle: username/model-name/pytorch/base
Message: initial version
License: Apache-2.0</pre>

<h2 id="system">7. System and Advanced</h2><ul><li><strong>Diagnostics</strong> checks runtime and authentication.</li><li><strong>Usage</strong> displays built-in examples.</li><li><strong>Completions</strong> prints definitions without modifying shell files.</li><li><strong>Advanced</strong> runs uncommon non-interactive option combinations without using a shell.</li></ul><p>To install or refresh shell completions on this workstation, run <code>kgnite completions</code> in a terminal after installing or updating kgnite. It writes files under <code>~/.local/share/kgnite/completions</code> and prints the line to add to <code>~/.zshrc</code> or <code>~/.bashrc</code>. On another workstation, install or update kgnite there first, then run the same command.</p><pre>kgnite search kernels rag --language python --kernel-type notebook --json</pre><p>Recursive <code>web</code> and terminal-interactive <code>browse</code> commands are blocked. Discover and Resources replace the terminal browse workflow.</p>

<h2 id="results">8. Table and JSON results</h2><p>Arrays of rows open in Table view with sticky headers. Select JSON for raw fields, nested values, or machine-readable copying. Plain-text commands automatically use a text panel.</p>

<h2 id="troubleshooting">9. Troubleshooting</h2><h3>401 or 403</h3><p>Run Diagnostics, verify credentials and competition-rule acceptance, and confirm that a resource handle—not a query—was entered.</p><h3>Command timeout</h3><pre>kgnite web --command-timeout 1800</pre><h3>Feature missing after an update</h3><pre>"$HOME/.local/share/kgnite/venv/bin/pip" install --no-deps --force-reinstall .
kgnite web</pre><h3>Browser does not open</h3><p>Use <code>kgnite web --no-browser</code> and copy the printed URL into a browser on the same workstation.</p>

<h2 id="security">10. Security and shutdown</h2><ul><li>Localhost-only binding.</li><li>Random per-session API token.</li><li>No shell execution.</li><li>External values rendered as text, not HTML.</li><li>Heartbeat-based shutdown after the page closes.</li></ul><p>For the complete repository version of this guide, see <code>WEB_GUIDE.md</code>.</p>
</main><script>const token={safe_token};async function beat(){{try{{await fetch('/api/heartbeat',{{method:'POST',headers:{{'X-Kgnite-Token':token}}}})}}catch(_){{}}}}beat();setInterval(beat,2000);</script></body></html>"""


def make_handler(session: WebSession) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "kgnite-web"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _headers(self, status: int, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'",
            )
            self.end_headers()

        def _json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
            body = json.dumps(payload).encode()
            self._headers(status, "application/json; charset=utf-8")
            self.wfile.write(body)

        def _authorized(self) -> bool:
            return secrets.compare_digest(
                self.headers.get("X-Kgnite-Token", ""), session.token
            )

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path not in {"/", "/guide"}:
                self._json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)
                return
            session.heartbeat()
            body = (
                guide_html(session.token).encode()
                if path == "/guide"
                else page_html(session.token, session.cwd).encode()
            )
            self._headers(HTTPStatus.OK, "text/html; charset=utf-8")
            self.wfile.write(body)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if not self._authorized():
                self._json(
                    {"ok": False, "error": "Invalid session token"},
                    HTTPStatus.FORBIDDEN,
                )
                return
            session.heartbeat()
            if path == "/api/heartbeat":
                self._json({"ok": True})
                return
            if path not in {"/api/run", "/api/upload"}:
                self._json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                request_limit = (
                    (MAX_UPLOAD_BYTES * 4 // 3) + 4096
                    if path == "/api/upload"
                    else MAX_BODY_BYTES
                )
                if length <= 0 or length > request_limit:
                    raise ValueError("Invalid request size.")
                payload = json.loads(self.rfile.read(length))
                if path == "/api/upload":
                    uploaded = save_uploaded_file(payload, session)
                    self._json({"ok": True, "path": str(uploaded)})
                    return
                arguments = payload.get("arguments")
                if arguments is None:
                    arguments = parse_command(str(payload.get("command", "")))
                if not isinstance(arguments, list) or not all(
                    isinstance(item, str) for item in arguments
                ):
                    raise ValueError("Arguments must be a list of strings.")
                response = run_command(arguments, session)
                self._json(
                    response,
                    HTTPStatus.OK if response["ok"] else HTTPStatus.BAD_REQUEST,
                )
            except (ValueError, TimeoutError, json.JSONDecodeError) as exc:
                self._json(
                    {
                        "ok": False,
                        "error": str(exc),
                        "stdout": "",
                        "stderr": str(exc),
                        "data": None,
                    },
                    HTTPStatus.BAD_REQUEST,
                )

    return Handler


def serve_web_app(
    *,
    port: int = 0,
    open_browser: bool = True,
    heartbeat_timeout: float = 30.0,
    command_timeout: float = 300.0,
) -> int:
    if not 0 <= port <= 65535:
        raise ValueError("Port must be between 0 and 65535.")
    if heartbeat_timeout < 5:
        raise ValueError("Heartbeat timeout must be at least 5 seconds.")
    if command_timeout <= 0:
        raise ValueError("Command timeout must be greater than zero.")
    upload_area = tempfile.TemporaryDirectory(prefix="kgnite-web-")
    session = WebSession(
        secrets.token_urlsafe(32),
        Path.cwd().resolve(),
        heartbeat_timeout,
        command_timeout,
        upload_dir=Path(upload_area.name),
    )
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(session))
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_port}/"

    def monitor() -> None:
        while True:
            time.sleep(1)
            if session.expired():
                server.shutdown()
                return

    threading.Thread(target=monitor, name="kgnite-web-heartbeat", daemon=True).start()
    print(f"kgnite web app: {url}")
    print(f"Workspace: {session.cwd}")
    print("Close the browser page to end the session, or press Ctrl+C.")
    if open_browser:
        webbrowser.open(url, new=2)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopping kgnite web app.")
    finally:
        server.server_close()
        upload_area.cleanup()
    return 0
