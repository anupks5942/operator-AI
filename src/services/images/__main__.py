"""CLI entry point: uv run python -m src.services.images.pipeline --source v22|bible|all"""
from src.services.images.pipeline import main

if __name__ == "__main__":
    main()
