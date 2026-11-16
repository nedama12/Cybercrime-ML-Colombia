"""Safe command-line entry point for cybercrime model experiments.

Production artifacts are never overwritten by this command. Candidates and
evaluation files are written to the isolated crime experiment locations.
"""
from __future__ import annotations


def main() -> None:
    """Run the leakage-aware experiment without promoting its candidate."""
    from src.experiment_crime import main as run_experiment

    run_experiment()


if __name__ == "__main__":
    main()
