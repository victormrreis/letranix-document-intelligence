import argparse
import json
import os
import threading
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="LETRANIX - Document Intelligence Platform")
    parser.add_argument(
        "command", choices=["serve", "demo", "fixtures", "evaluate", "mock-destination", "benchmark"]
    )
    parser.add_argument(
        "--data", type=Path, default=Path(os.environ.get("LETRANIX_DATA", ".runtime/workspace"))
    )
    parser.add_argument("--fixtures", type=Path, default=Path("demo/synthetic"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LETRANIX_PORT", "8795")))
    parser.add_argument(
        "--with-destination", action="store_true",
        help="Also run the fictitious records API on port+2 for the http-demo integration",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn

        from .app import create_app

        if args.with_destination:
            start_destination(args.data.parent / "destination", args.port + 2)
        app = create_app(args.data, Path(__file__).resolve().parent.parent / "dist")
        print(f"LETRANIX - http://127.0.0.1:{args.port} - workspace {args.data}")
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)
    elif args.command == "mock-destination":
        import uvicorn

        from .mock_destination import create_destination

        print(f"Fictitious records API - http://127.0.0.1:{args.port}/records")
        uvicorn.run(create_destination(args.data), host="127.0.0.1", port=args.port, access_log=False)
    elif args.command == "evaluate":
        from .evaluation import run_evaluation

        report = run_evaluation(Path(".runtime/evaluation"))
        text = json.dumps(report, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
        print(text)
    elif args.command == "benchmark":
        from .benchmark import run

        report = run(args.output)
        print(json.dumps(report, indent=2))
    else:
        from .demo import generate, seed

        if args.command == "fixtures":
            print(f"Generated {len(generate(args.fixtures))} synthetic documents")
        else:
            print(f"Added {seed(args.data, args.fixtures)} synthetic documents; existing data preserved")


def start_destination(data: Path, port: int):
    import uvicorn

    from .mock_destination import create_destination

    server = uvicorn.Server(uvicorn.Config(create_destination(data), host="127.0.0.1", port=port,
                                           access_log=False, log_level="warning"))
    threading.Thread(target=server.run, name="demo-destination", daemon=True).start()
    print(f"Fictitious records API - http://127.0.0.1:{port}/records")


if __name__ == "__main__":
    main()
