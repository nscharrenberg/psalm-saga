"""`python -m psalm_saga ...` — same as the `saga` command, without needing the generated
launcher executable (useful where policy blocks unsigned .exe files, e.g. managed Windows)."""

from psalm_saga.cli.main import app

if __name__ == "__main__":
    app(prog_name="saga")
