# Brain AI Project Studio 5.0

## Install

Download the latest Update_BrainAI.py, close Brain AI and run the updater using the Python environment selected in PyCharm. The updater locates the project or accepts --project with the Brain AI root. It backs up all replaced files before updating them. Restart desktop_app.py afterward.

## The ten additions

| Feature | Where and how it works |
| --- | --- |
| Fix this error | Games: Fix & retest. Uses the latest real test errors, edits files, validates syntax and APIs, saves a checkpoint, applies changes, then reruns tests. Setup/capture failures are kept separate from source errors. |
| Shared module contracts | Game menu: Shared module contracts. Before template edits, contracts.json records the public Game API. For custom builds, the manager records interfaces before the coder writes files, and static checks catch inconsistent imports, constructors and method calls. |
| Working foundations | Header: Templates. Choose platformer, racing or voxel. Create a playable foundation immediately, or give an AI customization request. The lightweight voxel foundation uses software 3D rendering with block breaking/placing. |
| Checkpoints / Undo | Game card: History. Restore a whole checkpoint or one file. Undo creates a new checkpoint, so the previous state remains recoverable. Favorites and chat history are preserved. |
| Gameplay tests | Test with AI runs movement, jump/landing, collision, win and lose assertions against the same Game class used during play. On Windows the visual startup/gameplay check also runs. |
| Compatible dependencies | Game menu: Check dependency compatibility. Resolves compatible binary wheels with pip's dry-run report. Python 3.14+ pygame pins are migrated to pygame-ce. Install dependencies also applies this fix and uses Python's pip module. |
| Resume builds | Game menu: Resume build. Saved build state keeps the task, plan, interfaces, completed files and failures. Valid files are retained, including manual edits. Projects without main.py still appear in Games. |
| Edit games in chat | Game card: Edit in chat. The header shows the selected game. Messages such as “add enemies” update that game's files. The context is stored with the chat. Leave game opens general chat. Explain and Quiz me stay conversational. |
| Agent dashboard | Header: Agents. Shows the manager/coder/vision request role, model, task, elapsed time, observed tokens/s, memory and errors. Model process RAM is available for servers owned by Brain AI; system RAM is sampled separately. |
| Demo export | Game menu: Export playable demo. Template/configuration games export to one offline HTML file with keyboard and touch controls. Custom Python logic/rendering exports to a source ZIP with a Windows launcher and setup instructions. |

## A short first run

1. Open Templates and select a game type.
2. Click Create playable template. The actual game-rule checks run immediately.
3. Open the new game in Games and click Play.
4. Choose Edit in chat and describe one small change, for example “make the level harder and change its name.”
5. The manager selects files; the coder makes bounded edits; validation runs before source files are replaced. Checkpoints are automatic.
6. Use History to undo, Fix & retest for a failing check, or Export playable demo to share the result.

## Commands

- /build <description>: create a project. Platformer/racing/voxel words select the relevant foundation.
- /edit <request>: update the game linked to the current game chat.
- /fix <optional error description>: use actual test evidence, apply a validated fix and retest.
- /resume: continue the linked project's saved build.

Pause task requests a stop. An owned local server can be interrupted; an external server's current response may need to finish first. Resume keeps successfully saved files. Closing the app midway through a request does not discard already saved project progress.

## What the test colors mean

Green means that the recorded test passed for the current source, configuration and requirements. Red includes untested, failed, incomplete and changed projects. Changing source or level.json invalidates the old pass; changing a favorite or cover does not. Refresh Games after external edits.

The five rule checks use deterministic fixtures, so they verify the actual engine mechanics rather than proving that every possible level is solvable. Compatible custom games can implement Game(config), configure_test(case), step(controls, dt) and snapshot() to use the same suite. Other games receive visual checks on Windows.

## Export scope

Offline HTML export is available while game_core.py and game_view.py match the foundation version; level.json customizations are included. The Python and JavaScript engines have matching scenario tests. If custom Python logic or rendering was added, source export preserves that code instead of pretending to translate arbitrary Python into JavaScript. The source demo requires Python to be installed; it includes RUN_WINDOWS.cmd and requirements.txt.

## Verification and limits

The foundations execute real Python gameplay assertions and were rendered with SDL's dummy video driver. Browser-engine scenarios are compared with Python using Node. Editing, repair, resume, dependency resolution and dashboard handling have integration tests, with local model responses mocked where model inference is involved. Actual GGUF inference and the Windows Tk/vision capture workflow still need validation on the target PC.
