import typer
from rich import Console

app = typer.Typer(
    name="psalm-saga",
    help="PSALM-SAGA: generate synthetic stories from scratch or from a source text.",
    no_args_is_help=True,
)
console = Console()

@app.command()
def new():
    """Start a new story-generation session"""
    pass

@app.command()
def resume():
    """Resume a session -- either continuing a pending question, or sending a new message."""
    pass

@app.command()
def batch():
    """Generate a labeled dataset for PSALM benchmarking: one story per (source, dimension) pair.

    Every session runs non-interactively -- no questions are asked -- with a pre-set
    divergence plan, so this can run unattended over many source files.
    """
    pass