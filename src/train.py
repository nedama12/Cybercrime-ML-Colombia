"""Safe entry point for the leakage-aware location benchmark experiment.

This command delegates to src.experiment_crime. Candidate artifacts and evaluation
outputs are written according to that module; it does not promote a candidate model.
It is separate from the incident narrative classifier (Astrith).
"""
from __future__ import annotations


def main() -> None:
    """Run the benchmark experiment without replacing the active production model."""
    from src.experiment_crime import main as run_experiment

    run_experiment()


if __name__ == "__main__":
    main()
