import typer
import environ
import webbrowser
import subprocess

from pathlib import Path
from functools import wraps


env = environ.Env()
INSIDE_DOCKER = env("INSIDE_DOCKER", default=False)
DOCKER_COMMAND_PREFIX = "docker-compose -f docker-compose.yml run --rm django /bin/bash -c".split()

COMMANDS = {
    "unittest_test": "python manage.py test --settings config.settings.test",
    "pytest_test": "pytest",
    "flake8": "flake8 .",
    "black": "black .",
    "coverage": (
        "coverage run --source='.' manage.py test --failfast "
        "--settings=config.settings.test && coverage report && "
        " coverage html"
    ),
    "docs": "cd docs && make html",
}


def typer_cli(f):
    # @app.command() does not work, dunno why
    @wraps(f)
    def wrapper():
        return typer.run(f)

    return wrapper


def print_styled_command(command):
    typer.echo(typer.style("Running command line:", fg=typer.colors.WHITE, bg=typer.colors.GREEN, bold=True,))
    typer.echo(typer.style(" ".join(command), bold=True) + "\n")


def run_command(command, debug=False):
    if not INSIDE_DOCKER:
        command = [*DOCKER_COMMAND_PREFIX, command]
    else:
        command = command.split()
    if debug:
        print_styled_command(command)
    subprocess.run(command)


@typer_cli
def test(test_path: str = typer.Argument(None)):
    command = COMMANDS["unittest_test"]
    if test_path is not None:
        command = f"{command} {test_path}"
    run_command(command, debug=True)


@typer_cli
def pytest(test_path: str = typer.Argument(None)):
    command = COMMANDS["pytest_test"]
    if test_path is not None:
        command = f"{command} {test_path}"
    run_command(command, debug=True)


@typer_cli
def flake8():
    command = COMMANDS["flake8"]
    run_command(command, debug=True)


@typer_cli
def black():
    command = COMMANDS["black"]
    run_command(command, debug=True)


@typer_cli
def coverage():
    command = COMMANDS["coverage"]
    run_command(command, debug=True)
    if not INSIDE_DOCKER:
        file_url = "file://" + str(Path("coverage/index.html").resolve())
        webbrowser.open_new_tab(file_url)


@typer_cli
def docs():
    command = COMMANDS["docs"]
    run_command(command, debug=True)
    if not INSIDE_DOCKER:
        file_url = "file://" + str(Path("docs/_build/html/index.html").resolve())
        webbrowser.open_new_tab(file_url)


@typer_cli
def command(name: str, debug: bool = False):
    command = COMMANDS.get(name, 'echo "no such command"')
    run_command(command, debug=debug)


@typer_cli
def shell():
    if INSIDE_DOCKER:
        return
    command = DOCKER_COMMAND_PREFIX[:-1]
    print_styled_command(command)
    subprocess.run(DOCKER_COMMAND_PREFIX[:-1])


@typer_cli
def attach(container_id: str):
    if INSIDE_DOCKER:
        return
    command = f"docker exec -it {container_id} /bin/bash".split()
    print_styled_command(command)
    subprocess.run(command)
