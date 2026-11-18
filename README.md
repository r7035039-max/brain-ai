[README_Brain_AI(2).md](https://github.com/user-attachments/files/35050753/README_Brain_AI.2.md)
# Brain Mini — Local AI Desktop Chat

Brain Mini is the first working foundation of **Brain AI**, a local desktop chat application based on the project's original `idea.txt` and `goals.txt`. It features a ChatGPT-inspired interface with Brain's own visual identity and connects to an existing `llama-server` instance. **Model weights are not included.**

## Getting Started (Windows / PyCharm)

1. Extract the project into a separate directory. Do not overwrite an older installation.
2. Use **Python 3.12 or 3.13** for compatibility with desktop dependencies. The backend was tested with Python 3.12; Python 3.14 and the native Windows desktop window have not been verified in the original test environment.
3. In the PyCharm terminal, run `python -m pip install -r requirements.txt`, or use `INSTALL.bat`.
4. Start your Qwen model with `llama-server` at `127.0.0.1:8080`. The application does **not** download or start the model automatically.
5. Run `main.py` in PyCharm or launch `START.bat`. The app opens in a standalone window; a browser is not required.
6. Look for the **Model connected** status in the bottom-left corner. If your model name differs from `Qwen3-4B`, set its exact name in Settings using the value returned by `http://127.0.0.1:8080/v1/models`.

The Windows desktop window uses **pywebview** and **Microsoft Edge WebView2 Runtime**. If WebView2 is missing, install the runtime from Microsoft. If desktop dependencies cause problems, use the explicit browser fallback:

```powershell
python main.py --browser
```

> **Dependency note:** The setup instructions reference `requirements.txt`. Ensure that this file is included in your distribution; the repository's current ignore rules may exclude `.txt` files.

## Features

- Dark and light themes, a green accent, and customizable accent colors.
- Streaming responses, stop and continue controls, text selection, and copying.
- Chat history with title search, renaming, pinning, deletion, and Markdown export.
- Projects with shared instructions (a “zero prompt”) and files accessible to all chats within a project.
- Text attachments, including TXT, Markdown, JSON, Python, HTML, and other source files up to **2 MB**. Files can be removed from context. JSON is treated as text, not as a structured record database.
- Code blocks with individual downloads and an isolated HTML preview that supports JavaScript.
- Read-only **FTS5 keyword search** over an existing `memory.db` archive, configured through Settings. The archive must provide a `messages_fts(text)` table, as used by `memory.py`.
- A confirmation-based sequential agent workflow: **manager → developer → reviewer → revision**. Plans and reviews appear in expandable stages and are saved in chat history.
- Python syntax validation using AST. Generated Python code is **not automatically executed** on your computer.
- Clear error messages for connection failures, empty responses, and context-window limits.

## Agents and 16 GB RAM

All agent roles call **one model sequentially**. The app does not keep four models loaded and does not load `transformers` or `torch` for these roles. Each role is a separate request with different instructions, rather than a separately trained neural network. A review does not guarantee that every bug will be fixed.

The initial settings use a **4,096-token context window** and a **1,400-token maximum response**. Game generation and multi-agent tasks generally benefit from a larger context, such as 8,192 tokens, configured both in `llama-server` and in the app. Changing the app setting does not change the server's actual context capacity.

RAM usage depends on the model, quantization, KV cache, and other running processes. Operation within 16 GB has not been benchmarked or guaranteed.

Token usage is estimated conservatively from UTF-8 text rather than calculated with the model's exact tokenizer. Older messages that do not fit into a request remain in the database. Automatic LLM-based conversation summarization is not yet implemented. File excerpts are selected through basic keyword overlap, not vector search. For large files, split the task into smaller requests.

In the agent workflow, generated code is passed to the reviewer and then returned to the developer along with the review. If the combined content exceeds the context window, the app reports an error and retains the code already produced. Increase the server and app context limits or reduce the task size.

## Try It

In a regular chat, try this prompt:

> Create a single, self-contained HTML file containing a simple driving game with obstacles, a score counter, and a restart button. Use arrow-key controls and no external libraries. Return the complete file in an HTML code block.

In **Agent Team** mode, confirm the four-stage workflow. Start with small prototypes. A full 3D project using Three.js requires the library or network access and must be run separately after downloading. Output quality depends on the connected model.

The built-in HTML preview blocks network requests and access to the parent application. HTML that depends on CDN-hosted libraries will not work inside the preview. Download and review such code before running it separately. Arbitrary HTML can also freeze itself through an infinite loop; if that happens, close the application window. Python games must be downloaded, reviewed, and run separately after installing their dependencies.

## Import Existing Chats

Close the new application. From a terminal in the project directory, run:

```powershell
python import_legacy.py "C:\path\to\old\desktop_chats.db"
```

The source database is opened **read-only**. Projects, instructions, chats, and messages are imported. Repeating an import from the same path does not duplicate messages.

Legacy `knowledge_records`, reasoning details, and settings are not migrated; attach the original files again if needed. `memory.db` is not imported—configure its path in Settings instead.

New application data is stored in `data/brain.db`. To make a backup, close the app and copy the `data` directory. Moving to another computer requires the source code, the data directory, and a separately installed model.

## Current Limitations

Brain Mini is a lightweight application, not a full GPT/Claude replacement or a newly trained foundation model. The version described here does not yet provide integrated web search, vision, automatic tester clicks, a secure sandbox for arbitrary code execution, image generation, PDF/OCR support, a Telegram bot, tool-driven settings management, LoRA training, dynamic loading and unloading of different models, or model-generated interactive questionnaires.

The HTML preview does support manually interacting with generated buttons and mini-apps.

LoRA adapters are loaded through `llama-server` and must be compatible with the base model. An adapter trained for a **0.6B** model cannot simply be attached to a **4B** model.

## Testing and Validation

Seven automated tests passed in the original test environment, covering streaming and persistence, sequential agent roles and follow-up requests, shared project context, stopping and preventing concurrent requests, context overflow, API unavailability, and local HTTP API protection.

These tests used a **mock SSE server**, not a real Qwen model. Python compilation passed, and JavaScript syntax was checked with Node.js.

A UI test script is included, but it could not be run in the original environment because Chromium was blocked. The actual UI, Windows/WebView2 behavior, performance, and output quality with Qwen still require testing on your own machine.

Run backend tests with:

```powershell
python -m unittest discover -s tests -v
```

For UI tests, install Playwright and Chromium separately. If necessary, adjust `executable_path` in `tests/ui_check.py`. These test dependencies are not required to use the application.

**pywebview API reference:** https://pywebview.flowrl.com/api/
