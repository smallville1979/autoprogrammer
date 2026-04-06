# folder-watcher

## Project Name
folder-watcher

## Description
A Python CLI tool that monitors a specified folder for new files and logs each detected file — along with a timestamp — to a CSV file. Designed to run continuously in the background, it is useful for auditing file drops, tracking incoming data exports, or debugging pipelines that write files to disk.

## Features
- Accepts a target folder path and output CSV path as CLI arguments
- Polls the target folder at a configurable interval (default: 5 seconds)
- Detects newly created files since the last poll
- Logs each new file with: filename, full path, file size in bytes, and ISO 8601 timestamp
- Appends to the CSV if it already exists; creates it with a header row if it does not
- Graceful shutdown on Ctrl+C with a confirmation message
- Validates that the target folder exists before starting
- Optional `--verbose` flag to also print each detected file to stdout

## File Structure
```
folder-watcher/
├── main.py          # Entry point: parses CLI args and starts the watcher loop
├── watcher.py       # Core logic: polls folder, compares file sets, yields new files
├── logger.py        # CSV writer: opens/creates the CSV, appends rows
├── config.py        # Constants and defaults (poll interval, CSV headers)
└── requirements.txt # Third-party dependencies
```

## Dependencies
- `watchdog` — optional enhanced file-system event backend (fallback: polling via `os.scandir`)
- `click` — CLI argument parsing
- `python-dateutil` — robust ISO 8601 timestamp formatting

Install with:
```
pip install -r requirements.txt
```

## Entry Point
```
python main.py --folder ./incoming --output ./log.csv --interval 5 --verbose
```

Arguments:
| Argument | Required | Default | Description |
|---|---|---|---|
| `--folder` | Yes | — | Path to the folder to monitor |
| `--output` | No | `file_log.csv` | Path to the output CSV file |
| `--interval` | No | `5` | Poll interval in seconds |
| `--verbose` | No | `False` | Print detections to stdout as well as CSV |
