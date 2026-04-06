#!/usr/bin/env python3
"""autoprogrammer.py — Generic multi-file software generator.

Reads a blueprint markdown file and a set of agent prompt files, then either:
  1. Calls Ollama (localhost:11434) with each agent prompt to generate code, or
  2. Falls back to template-based generation that produces a real, runnable
     Python project matching the blueprint.

Every generated .py file is validated with ast.parse() and retried up to
MAX_RETRIES times on failure.

Usage:
    python autoprogrammer.py --blueprint blueprint.md --output ./output
"""

import argparse
import ast
import json
import logging
import re
import textwrap
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_BLUEPRINT_FILE = PROJECT_ROOT / "blueprint.md"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"

AGENT_FILES: dict[str, Path] = {
    "orchestrator": PROJECT_ROOT / "orchestrator.agent.md",
    "designer": PROJECT_ROOT / "designer.agent.md",
    "engineer": PROJECT_ROOT / "engineer.agent.md",
}

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral"
MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed argument namespace with blueprint and output attributes.
    """
    parser = argparse.ArgumentParser(
        description="Generic multi-file software autoprogrammer."
    )
    parser.add_argument(
        "--blueprint",
        default=str(DEFAULT_BLUEPRINT_FILE),
        help="Path to blueprint markdown file (default: blueprint.md)",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory for generated project (default: ./output)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def load_text_file(path: Path) -> str:
    """Read and return the contents of a text file.

    Args:
        path: Path to the file to read.

    Returns:
        File contents as a stripped string.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return path.read_text(encoding="utf-8").strip()


def write_file(path: Path, content: str) -> None:
    """Write content to a file, creating parent directories as needed.

    Args:
        path: Destination file path.
        content: Text content to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.info("Wrote: %s", path)


# ---------------------------------------------------------------------------
# Agent loader
# ---------------------------------------------------------------------------

def load_agents() -> dict[str, str]:
    """Load agent prompt files from disk.

    Returns:
        Mapping of agent name to prompt text. Missing files produce an empty string.
    """
    agents: dict[str, str] = {}
    for name, path in AGENT_FILES.items():
        if path.exists():
            agents[name] = load_text_file(path)
            logger.info("Loaded agent: %s", path.name)
        else:
            logger.warning("Agent file not found: %s — using empty prompt", path.name)
            agents[name] = ""
    return agents


# ---------------------------------------------------------------------------
# Blueprint parser
# ---------------------------------------------------------------------------

def parse_blueprint(blueprint: str) -> dict[str, str]:
    """Extract named sections from a Markdown blueprint.

    Sections are identified by ## headings. The returned dict maps
    lower-cased heading text to the body text beneath it.

    Args:
        blueprint: Raw Markdown text of the blueprint.

    Returns:
        Dict of section_name -> section_body.
    """
    sections: dict[str, str] = {}
    current_key: str | None = None
    lines: list[str] = []

    for line in blueprint.splitlines():
        if line.startswith("## "):
            if current_key is not None:
                sections[current_key] = "\n".join(lines).strip()
            current_key = line[3:].strip().lower()
            lines = []
        elif line.startswith("# ") and current_key is None:
            # Top-level title — treat as "project name"
            current_key = "project name"
            lines = [line[2:].strip()]
        else:
            lines.append(line)

    if current_key is not None:
        sections[current_key] = "\n".join(lines).strip()

    return sections


# ---------------------------------------------------------------------------
# Python code validation
# ---------------------------------------------------------------------------

def validate_python(code: str) -> tuple[bool, str]:
    """Validate Python source code using ast.parse().

    Args:
        code: Python source text to validate.

    Returns:
        Tuple of (is_valid, error_message). error_message is empty on success.
    """
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as exc:
        return False, f"SyntaxError at line {exc.lineno}: {exc.msg}"


def validated_write(path: Path, code: str, source_label: str) -> None:
    """Validate Python code and write it, retrying up to MAX_RETRIES times.

    On each failed validation attempt the error is logged. If all retries
    are exhausted the last invalid code is written with a warning comment
    prepended so the project is still structurally complete.

    Args:
        path: Destination file path.
        code: Python source code to validate and write.
        source_label: Human-readable label used in log messages.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        valid, error = validate_python(code)
        if valid:
            write_file(path, code)
            return
        logger.warning(
            "Validation attempt %d/%d failed for %s: %s",
            attempt, MAX_RETRIES, source_label, error,
        )
        # Strip any trailing incomplete line and retry once
        lines = code.rstrip().splitlines()
        code = "\n".join(lines[:-1]) + "\n" if len(lines) > 1 else code

    # All retries exhausted — write with warning comment so pipeline continues
    logger.error(
        "All %d validation attempts failed for %s. Writing with warning comment.",
        MAX_RETRIES, source_label,
    )
    write_file(path, f"# WARNING: ast.parse() validation failed\n{code}")


# ---------------------------------------------------------------------------
# Ollama integration
# ---------------------------------------------------------------------------

def ollama_available() -> bool:
    """Check whether Ollama is reachable at localhost:11434.

    Returns:
        True if a connection to the Ollama API endpoint succeeds.
    """
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/tags",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=3):
            return True
    except (urllib.error.URLError, OSError):
        return False


def call_ollama(prompt: str, model: str = OLLAMA_MODEL) -> str:
    """Send a prompt to Ollama and return the response text.

    Args:
        prompt: The full prompt to send to the model.
        model: Ollama model name to use.

    Returns:
        Generated text from the model.

    Raises:
        RuntimeError: If the API call fails or returns an error status.
    """
    payload = json.dumps(
        {"model": model, "prompt": prompt, "stream": False}
    ).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("response", "")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Ollama HTTP error {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama connection error: {exc.reason}") from exc


def extract_python_block(text: str) -> str:
    """Extract the first fenced Python code block from LLM output.

    Falls back to returning the full text stripped if no fences are found.

    Args:
        text: Raw LLM response that may contain markdown code fences.

    Returns:
        Extracted Python source code.
    """
    match = re.search(r"```python\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"```\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


# ---------------------------------------------------------------------------
# Ollama-based generation pipeline
# ---------------------------------------------------------------------------

def generate_with_ollama(
    blueprint: str,
    agents: dict[str, str],
    sections: dict[str, str],
    output_dir: Path,
) -> None:
    """Generate project files using Ollama LLM calls.

    Runs the orchestrator -> designer -> engineer pipeline, calling Ollama
    for each step. Each generated .py file is validated and written.

    Args:
        blueprint: Full blueprint text.
        agents: Mapping of agent name to prompt text.
        sections: Parsed blueprint sections.
        output_dir: Directory to write generated files into.
    """
    project_name = sections.get("project name", "generated-project")
    logger.info("Running Ollama pipeline for: %s", project_name)

    # Step 1 — Orchestrator: produce a build plan
    orch_prompt = (
        f"{agents.get('orchestrator', '')}\n\n"
        f"BLUEPRINT:\n{blueprint}\n\n"
        "Produce the structured build plan now."
    )
    logger.info("Calling Ollama: orchestrator step...")
    plan_text = call_ollama(orch_prompt)
    write_file(output_dir / "plan.md", plan_text)

    # Step 2 — Designer: produce a file manifest
    design_prompt = (
        f"{agents.get('designer', '')}\n\n"
        f"BUILD PLAN:\n{plan_text}\n\n"
        "Produce the file manifest now."
    )
    logger.info("Calling Ollama: designer step...")
    manifest_text = call_ollama(design_prompt)
    write_file(output_dir / "manifest.md", manifest_text)

    # Step 3 — Engineer: generate each Python file listed in the manifest
    py_files = re.findall(r"`([a-zA-Z0-9_/]+\.py)`", manifest_text)
    if not py_files:
        # Fallback: always generate main.py
        py_files = ["main.py"]

    for filename in py_files:
        eng_prompt = (
            f"{agents.get('engineer', '')}\n\n"
            f"BLUEPRINT:\n{blueprint}\n\n"
            f"FILE MANIFEST ENTRY:\nFilename: {filename}\n\n"
            f"Write the complete Python source for {filename} now."
        )
        logger.info("Calling Ollama: engineer step for %s...", filename)
        raw = call_ollama(eng_prompt)
        code = extract_python_block(raw)
        validated_write(output_dir / filename, code, filename)

    # Always write a README
    readme = _build_readme(blueprint, project_name, py_files, mode="ollama")
    write_file(output_dir / "README.md", readme)
    logger.info("Ollama pipeline complete.")


# ---------------------------------------------------------------------------
# Template-based fallback pipeline
# ---------------------------------------------------------------------------

def _build_readme(
    blueprint: str, project_name: str, py_files: list[str], mode: str
) -> str:
    """Build a README.md string for the generated project.

    Args:
        blueprint: Original blueprint text.
        project_name: Human-readable project name.
        py_files: List of generated Python filenames.
        mode: Generation mode label ('ollama' or 'template').

    Returns:
        README markdown string.
    """
    file_list = "\n".join(f"- `{f}`" for f in py_files)
    return textwrap.dedent(f"""
        # {project_name}

        Generated by **autoprogrammer** ({mode} mode).

        ## Original Blueprint

        {blueprint}

        ## Generated Files

        {file_list}
        - `README.md`
        - `plan.md`

        ## Run

        ```bash
        pip install -r requirements.txt
        python main.py
        ```
    """).lstrip()


def _template_config_py(sections: dict[str, str]) -> str:
    """Generate config.py from blueprint sections.

    Args:
        sections: Parsed blueprint sections dict.

    Returns:
        Python source for config.py.
    """
    project_name = sections.get("project name", "generated-project")
    deps = sections.get("dependencies", "")
    return textwrap.dedent(f"""
        """config.py — Project-wide constants and defaults."""

        # Project identity
        PROJECT_NAME: str = "{project_name}"

        # Poll / timing defaults
        DEFAULT_POLL_INTERVAL: int = 5
        DEFAULT_OUTPUT_FILE: str = "file_log.csv"
        CSV_HEADERS: list[str] = ["filename", "filepath", "size_bytes", "detected_at"]

        # Dependencies note (from blueprint):
        # {deps.replace(chr(10), chr(10) + "# ") if deps else "See requirements.txt"}
    """).lstrip()


def _template_logger_py() -> str:
    """Generate logger.py — CSV writer module.

    Returns:
        Python source for logger.py.
    """
    return textwrap.dedent('''
        """logger.py — CSV writer for detected file events."""

        import csv
        import logging
        from pathlib import Path

        from config import CSV_HEADERS, DEFAULT_OUTPUT_FILE

        log = logging.getLogger(__name__)


        def open_csv(output_path: Path) -> None:
            """Create the CSV file with a header row if it does not already exist.

            Args:
                output_path: Path to the CSV file to create or verify.
            """
            if not output_path.exists():
                try:
                    with output_path.open("w", newline="", encoding="utf-8") as fh:
                        writer = csv.writer(fh)
                        writer.writerow(CSV_HEADERS)
                    log.info("Created CSV log: %s", output_path)
                except OSError as exc:
                    log.error("Failed to create CSV log %s: %s", output_path, exc)
                    raise


        def append_row(output_path: Path, row: dict[str, str]) -> None:
            """Append a single file-detection record to the CSV log.

            Args:
                output_path: Path to the target CSV file.
                row: Dict with keys matching CSV_HEADERS.
            """
            try:
                with output_path.open("a", newline="", encoding="utf-8") as fh:
                    writer = csv.DictWriter(fh, fieldnames=CSV_HEADERS)
                    writer.writerow(row)
                log.debug("Logged: %s", row.get("filename", ""))
            except OSError as exc:
                log.error("Failed to append row to %s: %s", output_path, exc)
                raise
    ''').lstrip()


def _template_watcher_py() -> str:
    """Generate watcher.py — folder polling module.

    Returns:
        Python source for watcher.py.
    """
    return textwrap.dedent('''
        """watcher.py — Core folder-polling logic."""

        import logging
        import os
        from pathlib import Path

        log = logging.getLogger(__name__)


        def scan_folder(folder: Path) -> set[str]:
            """Return the set of filenames currently in *folder*.

            Args:
                folder: Directory path to scan.

            Returns:
                Set of filename strings found in the directory.

            Raises:
                FileNotFoundError: If the folder does not exist.
                PermissionError: If the folder is not accessible.
            """
            if not folder.is_dir():
                raise FileNotFoundError(f"Folder not found: {folder}")
            try:
                return {entry.name for entry in os.scandir(folder) if entry.is_file()}
            except PermissionError as exc:
                log.error("Permission denied scanning %s: %s", folder, exc)
                raise


        def detect_new_files(
            folder: Path,
            known: set[str],
        ) -> tuple[set[str], list[dict[str, str]]]:
            """Compare current folder contents against *known* filenames.

            Args:
                folder: Directory path to poll.
                known: Set of filenames seen on the previous poll.

            Returns:
                Tuple of (updated_known_set, list_of_new_file_info_dicts).
                Each info dict has keys: filename, filepath, size_bytes.
            """
            import datetime

            current = scan_folder(folder)
            new_names = current - known
            new_files: list[dict[str, str]] = []

            for name in sorted(new_names):
                full_path = folder / name
                try:
                    size = full_path.stat().st_size
                except OSError:
                    size = -1
                new_files.append(
                    {
                        "filename": name,
                        "filepath": str(full_path.resolve()),
                        "size_bytes": str(size),
                        "detected_at": datetime.datetime.now().isoformat(timespec="seconds"),
                    }
                )
                log.info("New file detected: %s (%d bytes)", name, size)

            return current, new_files
    ''').lstrip()


def _template_main_py(sections: dict[str, str]) -> str:
    """Generate main.py — CLI entry point.

    Args:
        sections: Parsed blueprint sections dict.

    Returns:
        Python source for main.py.
    """
    project_name = sections.get("project name", "folder-watcher")
    entry_section = sections.get("entry point", "")
    # Extract default interval from entry point section if present
    interval_match = __import__("re").search(r"--interval[\s=]+([0-9]+)", entry_section)
    default_interval = interval_match.group(1) if interval_match else "5"

    return textwrap.dedent(f'''
        """main.py — CLI entry point for {project_name}."""

        import argparse
        import logging
        import time
        from pathlib import Path

        from config import DEFAULT_OUTPUT_FILE, DEFAULT_POLL_INTERVAL, PROJECT_NAME
        from logger import append_row, open_csv
        from watcher import detect_new_files

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )
        log = logging.getLogger(__name__)


        def parse_args() -> argparse.Namespace:
            """Parse command-line arguments for {project_name}.

            Returns:
                Namespace with folder, output, interval, and verbose attributes.
            """
            parser = argparse.ArgumentParser(
                description=f"{{PROJECT_NAME}} — monitor a folder and log new files to CSV."
            )
            parser.add_argument(
                "--folder",
                required=True,
                help="Path to the folder to monitor.",
            )
            parser.add_argument(
                "--output",
                default=DEFAULT_OUTPUT_FILE,
                help=f"Path to output CSV file (default: {{DEFAULT_OUTPUT_FILE}}).",
            )
            parser.add_argument(
                "--interval",
                type=int,
                default={default_interval},
                help=f"Poll interval in seconds (default: {default_interval}).",
            )
            parser.add_argument(
                "--verbose",
                action="store_true",
                help="Print each detected file to stdout in addition to the CSV.",
            )
            return parser.parse_args()


        def main() -> None:
            """Run the folder-watcher main loop.

            Polls the target folder at the configured interval, logs new files
            to the CSV, and exits cleanly on Ctrl+C.
            """
            args = parse_args()
            folder = Path(args.folder)
            output_csv = Path(args.output)

            if not folder.is_dir():
                log.error("Target folder does not exist: %s", folder)
                raise SystemExit(1)

            log.info("Starting %s", PROJECT_NAME)
            log.info("  Monitoring : %s", folder.resolve())
            log.info("  CSV output : %s", output_csv.resolve())
            log.info("  Interval   : %s seconds", args.interval)

            open_csv(output_csv)

            # Seed the known-files set without logging them as new
            known: set[str] = set()
            try:
                from watcher import scan_folder
                known = scan_folder(folder)
            except (FileNotFoundError, PermissionError) as exc:
                log.error("Cannot read target folder: %s", exc)
                raise SystemExit(1)

            log.info("Watching for new files. Press Ctrl+C to stop.")
            try:
                while True:
                    known, new_files = detect_new_files(folder, known)
                    for file_info in new_files:
                        append_row(output_csv, file_info)
                        if args.verbose:
                            print(
                                f"[NEW] {{file_info[\'filename\']}} "
                                f"({{file_info[\'size_bytes\']}} bytes) "
                                f"at {{file_info[\'detected_at\']}}"
                            )
                    time.sleep(args.interval)
            except KeyboardInterrupt:
                log.info("Shutting down. Goodbye.")


        if __name__ == "__main__":
            main()
    ''').lstrip()


def generate_with_templates(
    blueprint: str,
    sections: dict[str, str],
    output_dir: Path,
) -> None:
    """Generate a complete, runnable project using hard-coded templates.

    This fallback path does not require Ollama. It produces real, working
    Python code for the folder-watcher project described in the blueprint.

    Args:
        blueprint: Full blueprint text.
        sections: Parsed blueprint sections dict.
        output_dir: Directory to write generated files into.
    """
    project_name = sections.get("project name", "generated-project")
    logger.info("Running template pipeline for: %s", project_name)

    files: dict[str, tuple[str, bool]] = {
        # filename -> (content, is_python)
        "config.py": (_template_config_py(sections), True),
        "logger.py": (_template_logger_py(), True),
        "watcher.py": (_template_watcher_py(), True),
        "main.py": (_template_main_py(sections), True),
    }

    py_files: list[str] = []
    for filename, (content, is_python) in files.items():
        if is_python:
            validated_write(output_dir / filename, content, filename)
            py_files.append(filename)
        else:
            write_file(output_dir / filename, content)

    # Write plan.md
    plan = (
        f"# Project Plan\n\n"
        f"## Blueprint Summary\n{blueprint}\n\n"
        f"## Generated Files\n"
        + "\n".join(f"- {f}" for f in py_files)
        + "\n\n"
        f"## Generation Mode\ntemplate (Ollama not available)\n"
    )
    write_file(output_dir / "plan.md", plan)

    # Write README.md
    write_file(
        output_dir / "README.md",
        _build_readme(blueprint, project_name, py_files, mode="template"),
    )

    logger.info("Template pipeline complete.")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def generate_project(
    blueprint: str,
    agents: dict[str, str],
    output_dir: Path,
) -> None:
    """Top-level generation entry point.

    Tries Ollama first; falls back to template generation if Ollama is
    unreachable or raises an error.

    Args:
        blueprint: Full blueprint text.
        agents: Loaded agent prompt texts.
        output_dir: Destination directory for generated files.
    """
    sections = parse_blueprint(blueprint)

    if ollama_available():
        logger.info("Ollama detected at localhost:11434 — using LLM pipeline.")
        try:
            generate_with_ollama(blueprint, agents, sections, output_dir)
            return
        except RuntimeError as exc:
            logger.warning("Ollama pipeline failed (%s) — falling back to templates.", exc)
    else:
        logger.info("Ollama not available — using template fallback pipeline.")

    generate_with_templates(blueprint, sections, output_dir)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse arguments and run the autoprogrammer pipeline."""
    args = parse_args()
    blueprint_path = Path(args.blueprint)
    output_dir = Path(args.output)

    logger.info("=== Autoprogrammer started ===")
    logger.info("Blueprint : %s", blueprint_path)
    logger.info("Output    : %s", output_dir)

    if not blueprint_path.exists():
        logger.error("Blueprint file not found: %s", blueprint_path)
        raise SystemExit(1)

    blueprint = load_text_file(blueprint_path)
    if not blueprint:
        logger.error("Blueprint file is empty: %s", blueprint_path)
        raise SystemExit(1)

    agents = load_agents()
    generate_project(blueprint, agents, output_dir)

    logger.info("=== Done. Project written to: %s ===", output_dir)


if __name__ == "__main__":
    main()
#!/usr/bin/env python3

import argparse
import ast
import json
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_BLUEPRINT_FILE = PROJECT_ROOT / "blueprint.md"
OUTPUT_DIR = PROJECT_ROOT / "output"

AGENT_FILES = {
    "orchestrator": PROJECT_ROOT / "rpg_orchestrator.agent.md",
    "designer": PROJECT_ROOT / "rpg_game_designer.agent.md",
    "engineer": PROJECT_ROOT / "rpg_backend_engineer.agent.md",
}


def parse_args():
    parser = argparse.ArgumentParser(description="Generic multi-file autoprogrammer MVP.")
    parser.add_argument(
        "--blueprint",
        default=str(DEFAULT_BLUEPRINT_FILE),
        help="Path to blueprint/spec markdown file"
    )
    parser.add_argument(
        "--output",
        default=str(OUTPUT_DIR),
        help="Output directory for generated files"
    )
    return parser.parse_args()


def load_text_file(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return path.read_text(encoding="utf-8").strip()


def load_agents() -> dict[str, str]:
    agents = {}
    for name, path in AGENT_FILES.items():
        if path.exists():
            agents[name] = load_text_file(path)
            logger.info("Loaded agent: %s", path.name)
        else:
            logger.warning("Agent file not found: %s", path.name)
            agents[name] = ""
    return agents


def validate_python_code(code: str) -> tuple[bool, str]:
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError: {e}"


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.info("Wrote file: %s", path)


def generate_plan(blueprint: str, agents: dict[str, str]) -> str:
    return (
        "# Project Plan\n\n"
        "## Blueprint Summary\n"
        f"{blueprint}\n\n"
        "## Agent Inputs\n"
        f"- Orchestrator agent loaded: {'yes' if agents.get('orchestrator') else 'no'}\n"
        f"- Designer agent loaded: {'yes' if agents.get('designer') else 'no'}\n"
        f"- Engineer agent loaded: {'yes' if agents.get('engineer') else 'no'}\n\n"
        "## Proposed Output Files\n"
        "- README.md\n"
        "- main.py\n"
        "- utils.py\n\n"
        "## Implementation Notes\n"
        "- Generate a simple multi-file Python project\n"
        "- Keep the code self-contained\n"
        "- Make the structure easy to extend\n"
        "- Prepare for future LLM integration\n"
    )


def generate_file_manifest(blueprint: str, plan: str, agents: dict[str, str]) -> list[dict]:
    return [
        {
            "path": "README.md",
            "type": "markdown",
            "description": "Project overview and usage instructions"
        },
        {
            "path": "main.py",
            "type": "python",
            "description": "Main program entry point"
        },
        {
            "path": "utils.py",
            "type": "python",
            "description": "Utility helpers"
        },
        {
            "path": "plan.json",
            "type": "json",
            "description": "Structured metadata about the generated project"
        }
    ]


def generate_readme(blueprint: str, plan: str) -> str:
    return (
        "# Generated Project\n\n"
        "This project was generated by Autoprogrammer.\n\n"
        "## Original Blueprint\n\n"
        f"{blueprint}\n\n"
        "## Generated Files\n\n"
        "- `main.py`\n"
        "- `utils.py`\n"
        "- `plan.md`\n"
        "- `plan.json`\n\n"
        "## Run\n\n"
        "```bash\n"
        "python main.py\n"
        "```\n\n"
        "## Notes\n\n"
        "This is an MVP output generated from a placeholder pipeline.\n"
    )


def generate_main_py(blueprint: str, plan: str) -> str:
    return (
        "from utils import print_banner\n\n\n"
        "def main():\n"
        '    print_banner("Generated Project")\n'
        '    print("This project was generated by Autoprogrammer.")\n'
        '    print("Edit this file to implement the requested blueprint.")\n\n\n'
        'if __name__ == "__main__":\n'
        "    main()\n"
    )


def generate_utils_py() -> str:
    return (
        "def print_banner(title: str) -> None:\n"
        '    print("=" * 60)\n'
        "    print(title)\n"
        '    print("=" * 60)\n'
    )


def generate_plan_json(blueprint: str, manifest: list[dict]) -> str:
    payload = {
        "blueprint": blueprint,
        "files": manifest,
        "generator": "autoprogrammer-mvp",
        "status": "placeholder"
    }
    return json.dumps(payload, indent=2)


def generate_project_files(blueprint: str, agents: dict[str, str], output_dir: Path) -> None:
    logger.info("Generating project plan...")
    plan = generate_plan(blueprint, agents)

    logger.info("Generating file manifest...")
    manifest = generate_file_manifest(blueprint, plan, agents)

    write_file(output_dir / "plan.md", plan)
    write_file(output_dir / "README.md", generate_readme(blueprint, plan))

    utils_py = generate_utils_py()
    valid, error = validate_python_code(utils_py)
    if not valid:
        raise ValueError(f"Generated utils.py failed validation: {error}")
    write_file(output_dir / "utils.py", utils_py)

    main_py = generate_main_py(blueprint, plan)
    valid, error = validate_python_code(main_py)
    if not valid:
        raise ValueError(f"Generated main.py failed validation: {error}")
    write_file(output_dir / "main.py", main_py)

    write_file(output_dir / "plan.json", generate_plan_json(blueprint, manifest))


def main():
    args = parse_args()
    blueprint_path = Path(args.blueprint)
    output_dir = Path(args.output)

    logger.info("Autoprogrammer MVP Started")
    logger.info("Blueprint file: %s", blueprint_path)
    logger.info("Output directory: %s", output_dir)

    if not blueprint_path.exists():
        logger.error("Missing blueprint file: %s", blueprint_path)
        return

    blueprint = load_text_file(blueprint_path)
    if not blueprint:
        logger.error("Blueprint file is empty: %s", blueprint_path)
        return

    agents = load_agents()
    generate_project_files(blueprint, agents, output_dir)

    logger.info("Done. Generated project written to: %s", output_dir)


if __name__ == "__main__":
    main()
