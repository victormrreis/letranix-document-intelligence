import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="LETRANIX â€” Document Intelligence Platform")
    parser.add_argument("command", choices=["serve", "demo", "fixtures"])
    parser.add_argument(
        "--data", type=Path, default=Path(os.environ.get("LETRANIX_DATA", ".runtime/workspace"))
    )
    parser.add_argument("--fixtures", type=Path, default=Path("demo/synthetic"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LETRANIX_PORT", "8795")))
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn
        from .app import create_app

        app = create_app(args.data, Path(__file__).resolve().parent.parent / "dist")
        print(f"LETRANIX Â· http://127.0.0.1:{args.port} Â· local demo integration only")
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)
    else:
        from .demo import generate, seed

        if args.command == "fixtures":
            print(f"Generated {len(generate(args.fixtures))} synthetic documents")
        else:
            print(
                f"Added {seed(args.data, args.fixtures)} synthetic documents; existing data preserved"
            )


if __name__ == "__main__":
    main()
