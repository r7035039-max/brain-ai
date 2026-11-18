"""Start Brain AI in Tkinter or download its local models."""
from __future__ import annotations

import argparse

from model_runtime import MODELS, ModelUnavailable, download_models, model_paths, runtime


def main() -> None:
    parser = argparse.ArgumentParser(description="Brain AI local desktop app")
    parser.add_argument("--download-models", nargs="*", choices=tuple(MODELS),
                        help="download all models, or select chat, coder, or vision")
    args = parser.parse_args()
    if args.download_models is not None:
        try:
            download_models(args.download_models or list(MODELS))
        except (OSError, ModelUnavailable) as error:
            parser.exit(1, f"{error}\n")
        return

    import tkinter as tk

    from desktop_app import App, init_db

    init_db()
    root = tk.Tk()
    app = App(root)
    if model_paths("chat")[0]:
        app.set_status("Ready · Models load when needed")
    else:
        app.set_status("Set up local models with: python main.py --download-models")
    try:
        root.mainloop()
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
