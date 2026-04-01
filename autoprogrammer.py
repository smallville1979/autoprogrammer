#!/usr/bin/env python3

import argparse
import ast
import logging
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
SRC_DIR = PROJECT_ROOT / "src"

DIST_DIR.mkdir(exist_ok=True)
BUILD_DIR.mkdir(exist_ok=True)
SRC_DIR.mkdir(exist_ok=True)

DEFAULT_BLUEPRINT_FILE = PROJECT_ROOT / "blueprint.md"
DEFAULT_GAME_FILE = SRC_DIR / "game.py"
DEFAULT_GAME_NAME = "LegendsOfPandora"
MAX_ATTEMPTS = 5


def parse_args():
    parser = argparse.ArgumentParser(description="Generate and build a Pygame RPG from a blueprint.")
    parser.add_argument(
        "--blueprint",
        default=str(DEFAULT_BLUEPRINT_FILE),
        help="Path to blueprint markdown file"
    )
    parser.add_argument(
        "--name",
        default=DEFAULT_GAME_NAME,
        help="Name of the built game executable"
    )
    return parser.parse_args()


def check_python_package(package_name: str) -> bool:
    try:
        __import__(package_name)
        return True
    except ImportError:
        return False


def extract_code_block(text: str) -> str:
    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            return "\n".join(lines).strip()

    return text


def generate_code(blueprint_text: str, previous_error: str = "") -> str:
    """
    Placeholder generator.
    Replace later with Ollama, OpenAI, Anthropic, Grok, etc.
    """
    prompt = f"""
You are an expert game developer. Create a complete, standalone Python game using Pygame based on this blueprint:

{blueprint_text}
"""

    if previous_error:
        prompt += f"""

Previous build failed with these errors:
{previous_error}

Fix them and regenerate the full code.
"""

    prompt += """
Requirements:
- Use Pygame for a windowed text-based RPG
- Include character creation, combat, quests, romance options
- No external files or assets needed
- Full code in one file
- Working main loop with event handling
- Print "Game Ready!" on start

Output ONLY the Python code. No explanations.
"""

    logger.info("Generating code (placeholder LLM)...")
    time.sleep(1)

    placeholder_code = '''import pygame
import sys

print("Game Ready!")

pygame.init()
screen = pygame.display.set_mode((1000, 700))
pygame.display.set_caption("Legends of Pandora")
clock = pygame.time.Clock()
font = pygame.font.Font(None, 36)

player_name = "Hero"

def draw_text(text, x, y, color=(255, 255, 255)):
    surface = font.render(text, True, color)
    screen.blit(surface, (x, y))

running = True
while running:
    screen.fill((0, 0, 0))

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            running = False

    draw_text("=== LEGENDS OF PANDORA ===", 50, 50)
    draw_text(f"Welcome, {player_name}!", 50, 120)
    draw_text("You awaken in Arcadian Town Square...", 50, 180)
    draw_text("Features to expand: combat, quests, romance, character creation", 50, 240)
    draw_text("Press ESC to exit", 50, 500)

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
sys.exit()
'''
    return extract_code_block(placeholder_code)


def validate_python_code(code: str) -> tuple[bool, str]:
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError: {e}"


def write_game_file(game_file: Path, code: str) -> None:
    game_file.write_text(code, encoding="utf-8")
    logger.info("Code written to %s", game_file)


def run_python_smoke_check(game_file: Path) -> tuple[bool, str]:
    cmd = [sys.executable, "-m", "py_compile", str(game_file)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return True, ""
    return False, result.stderr + result.stdout


def compile_game(game_file: Path, game_name: str) -> tuple[bool, str]:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", game_name,
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--specpath", str(PROJECT_ROOT),
        str(game_file),
    ]
    logger.info("Compiling with PyInstaller...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        logger.info("Build SUCCESS!")
        return True, ""
    logger.error("Build FAILED.")
    return False, result.stderr + result.stdout


def ensure_requirements() -> bool:
    ok = True

    if not check_python_package("PyInstaller"):
        logger.error("PyInstaller is not installed for this Python version.")
        logger.error("Install with: py -3.12 -m pip install pyinstaller")
        ok = False

    if not check_python_package("pygame"):
        logger.error("pygame is not installed.")
        logger.error("Install with: py -3.12 -m pip install pygame")
        ok = False

    return ok


def clean_old_artifacts(game_name: str):
    spec_file = PROJECT_ROOT / f"{game_name}.spec"
    if spec_file.exists():
        spec_file.unlink()
        logger.info("Removed old spec file: %s", spec_file)


def main():
    args = parse_args()
    blueprint_file = Path(args.blueprint)
    game_name = args.name
    game_file = DEFAULT_GAME_FILE

    logger.info("Autoprogrammer Started")
    logger.info("Blueprint file: %s", blueprint_file)
    logger.info("Game name: %s", game_name)

    if not ensure_requirements():
        return

    if not blueprint_file.exists():
        logger.error("Missing blueprint file: %s", blueprint_file)
        return

    blueprint = blueprint_file.read_text(encoding="utf-8").strip()
    if not blueprint:
        logger.error("Blueprint file is empty: %s", blueprint_file)
        return

    attempts = 0
    last_error = ""

    while attempts < MAX_ATTEMPTS:
        attempts += 1
        logger.info("Attempt %s/%s", attempts, MAX_ATTEMPTS)

        code = generate_code(blueprint, last_error)

        valid, syntax_error = validate_python_code(code)
        if not valid:
            last_error = syntax_error
            logger.warning("Generated code failed AST validation: %s", syntax_error)
            continue

        write_game_file(game_file, code)

        smoke_ok, smoke_error = run_python_smoke_check(game_file)
        if not smoke_ok:
            last_error = smoke_error[-2000:]
            logger.warning("Smoke check failed. Retrying with error feedback...")
            continue

        clean_old_artifacts(game_name)

        success, error = compile_game(game_file, game_name)
        if success:
            exe_path = DIST_DIR / f"{game_name}.exe"
            logger.info("DONE! Your game is ready: %s", exe_path)
            logger.info("Send this .exe to your friend — no Python needed on their end!")
            return

        last_error = error[-2000:]
        logger.warning("Fixing errors and retrying...")

    logger.error("Failed after max attempts. Check logs.")


if __name__ == "__main__":
    main()