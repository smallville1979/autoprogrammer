# Autoprogrammer

Autoprogrammer is a software generator that turns a high-level software blueprint into a runnable Python project using AI agents.

Given a structured blueprint describing modules, data models, and behaviours, Autoprogrammer:
- Reads and validates the blueprint.
- Uses AI agent prompts to generate real Python packages, modules, and configuration files.
- Runs automated validation to catch syntax and basic logic issues.
- Outputs a ready‑to‑run Python project on disk.

All previous RPG / game‑style metaphors have been removed; this tool now focuses purely on software generation.

## Features

- Blueprint‑driven generation (projects are defined declaratively).
- Multi‑agent AI workflow for code, tests, and docs.
- Automatic code validation (linting and basic checks).
- Deterministic output folder structure for easy deployment.

## Requirements

- Python 3.10+ installed.
- An API key for the configured AI provider (e.g. Anthropic, OpenAI, etc.), exported as an environment variable.
- Git and a POSIX‑like shell (PowerShell or WSL on Windows work fine).

## Installation

Clone the repository:

```bash
git clone https://github.com/smallville1979/autoprogrammer.git
cd autoprogrammer
```

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate    # Linux/macOS
# or
.\.venv\Scripts\activate     # Windows
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Set your AI key (example for Anthropic):

```bash
export ANTHROPIC_API_KEY="your-key-here"   # Linux/macOS
# or
setx ANTHROPIC_API_KEY "your-key-here"     # Windows (new shell needed)
```

## Usage

1. Write a blueprint file, for example `blueprint.yaml`:

```yaml
project_name: example_app
description: Simple generated Python service
modules:
  - name: core
    description: Core domain logic
  - name: api
    description: HTTP API layer
```

2. Run Autoprogrammer against the blueprint:

```bash
python -m autoprogrammer \
  --blueprint blueprint.yaml \
  --output ./generated_project
```

3. Inspect the generated project:

```bash
cd generated_project
python -m pip install -r requirements.txt
python -m pytest          # if tests were generated
python main.py            # or the entrypoint created by the blueprint
```

The tool will:
- Parse the blueprint.
- Call the AI agents to generate Python modules, tests, and config.
- Validate the code.
- Write all files into `generated_project/`.

## Development

To work on Autoprogrammer itself:

```bash
git clone https://github.com/smallville1979/autoprogrammer.git
cd autoprogrammer
python -m venv .venv
source .venv/bin/activate  # or .\.venv\Scripts\activate on Windows
pip install -r requirements-dev.txt
```

Run tests:

```bash
pytest
```

## License

See `LICENSE` in this repository.
