"""UI entry points for editing, repair, resume, history, templates and export."""
import json
import os
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import uuid

from model_runtime import runtime
from project_support import game_info, game_from_message, read_json
from project_tools import (atomic_json, checkpoints, restore_checkpoint, check_dependencies,
                           project_root, sources, extract_api)
from game_templates import TEMPLATES, seed_template, export_demo
from studio_metrics import memory_usage


class StudioMixin:
    def _host(self): return sys.modules[type(self).__module__]
    def _root(self): return Path(self._host().HERE).resolve()

    def __init__(self, root):
        self.editing_game = None
        self.build_cancelled = threading.Event()
        self.studio_context = None
        with self._host().connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS chat_games(chat_id INTEGER PRIMARY KEY, script TEXT NOT NULL)')
        super().__init__(root)
        self.root.title('Brain AI 2999 ELO | Project Studio')

    def build_shell(self):
        super().build_shell()
        c = self.colors
        bar = tk.Frame(self.header, bg=c['bg'])
        bar.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(5, 0))
        for label, action in [('Templates', self.show_template_picker), ('Agents', self.show_agent_dashboard),
                              ('Pause task', self.pause_studio_task), ('Leave game', self.leave_game_chat)]:
            self.small_button(bar, label, action).pack(side='left', padx=(0, 5))
        self.studio_context = tk.Label(bar, bg=c['bg'], fg=self.accent, font=(self.font, 9))
        self.studio_context.pack(side='right')
        self.update_studio_context()

    def update_studio_context(self):
        if self.studio_context is not None and self.studio_context.winfo_exists():
            label = 'Editing: ' + game_info(self.editing_game)['title'][:36] if self.editing_game and Path(self.editing_game).parent.is_dir() else 'General chat'
            self.studio_context.configure(text=label)

    def show_chat_page(self):
        super().show_chat_page()
        self.update_studio_context()

    def new_chat(self):
        selected_game = self.editing_game
        super().new_chat()
        with self._host().connect() as db:
            if selected_game:
                db.execute('INSERT OR REPLACE INTO chat_games(chat_id,script) VALUES(?,?)', (self.chat_id, str(selected_game)))
            else:
                db.execute('DELETE FROM chat_games WHERE chat_id=?', (self.chat_id,))
        self.editing_game = selected_game
        self.update_studio_context()

    def _chat_script(self, chat_id):
        with self._host().connect() as db:
            row = db.execute('SELECT script FROM chat_games WHERE chat_id=?', (chat_id,)).fetchone()
        if row:
            path = Path(row['script']).resolve()
            resumable = path.parent.is_dir() and ((path.parent / '.brain_build.json').is_file() or (path.parent / 'build_report.json').is_file())
            if (path.is_file() or resumable) and path.is_relative_to(self._root() / 'workspace'): return path
        return None

    def open_chat(self, chat_id):
        self.editing_game = self._chat_script(chat_id)
        super().open_chat(chat_id)
        self.update_studio_context()

    def open_game_chat(self, script):
        try:
            project_root(script, self._root())
        except ValueError as error:
            messagebox.showinfo('Edit game', str(error), parent=self.root)
            return
        self.editing_game = Path(script).resolve()
        with self._host().connect() as db:
            row = db.execute('SELECT c.id FROM chats c JOIN chat_games g ON g.chat_id=c.id WHERE g.script=? ORDER BY c.updated DESC LIMIT 1', (str(self.editing_game),)).fetchone()
        if row: self.open_chat(row['id'])
        else: self.new_chat()
        self.update_studio_context()
        self.set_status('Messages in this chat edit this game. Try “add enemies” or “make the level harder”.')

    def leave_game_chat(self):
        self.editing_game = None
        self.new_chat()
        self.update_studio_context()

    def send(self, _event=None):
        if self.current_page != 'chat': return 'break'
        if not self.busy:
            self.build_cancelled.clear()
            text = self.entry.get('1.0', 'end').strip()
            if self.editing_game and text and not text.startswith('/') and not getattr(self, '_plain_studio_reply', False):
                self.entry.delete('1.0', 'end')
                self.entry.insert('1.0', '/edit ' + text)
        return super().send(_event)

    def quick_reply(self, kind, content):
        self._plain_studio_reply = kind in {'explain', 'quiz'}
        try: return super().quick_reply(kind, content)
        finally: self._plain_studio_reply = False

    def worker(self, chat_id, messages, effort, question, sources_used):
        command, _, argument = question.partition(' ')
        if command not in {'/build', '/edit', '/fix', '/resume'}:
            return super().worker(chat_id, messages, effort, question, sources_used)
        def progress(text):
            if hasattr(runtime, 'report_task'): runtime.report_task(text)
            self.events.put(('progress', chat_id, text, None))
        try:
            from agent import build, edit_project, resume_project
            script = self._chat_script(chat_id)
            if command == '/build':
                answer = build(argument, progress, cancelled=self.build_cancelled)
            elif script is None:
                answer = 'Open Games and choose Edit in chat on the project first.'
            elif command == '/resume':
                answer = resume_project(script, progress, self.build_cancelled)
            else:
                instruction = argument or 'Fix the observed errors from the latest actual test report.'
                answer = edit_project(script, instruction, progress, repair=command == '/fix', cancelled=self.build_cancelled)
            self.finish_reply(chat_id, question, answer, 'Saved project changes have checkpoints. The report lists actual checks and remaining issues.', None)
        except Exception as error:
            self.events.put(('error', chat_id, str(error), None))

    def pause_studio_task(self):
        if not self.busy:
            self.set_status('No running task to pause.')
            return
        self.build_cancelled.set()
        self.test_cancelled.set()
        interrupted = runtime.interrupt() if hasattr(runtime, 'interrupt') else False
        self.set_status('Pausing. Completed files are saved for Resume.' if interrupted else
                        'Pause requested; it will stop after the current model response.')

    def _start_game_action(self, script, question, action):
        if self.busy:
            self.set_status('Finish or pause the current task first.')
            return False
        if script is not None:
            self.open_game_chat(script)
        elif self.editing_game:
            self.leave_game_chat()
        self.build_cancelled.clear()
        self.test_cancelled.clear()
        keep_alive = question.startswith(('Fix and retest:', 'Test game:'))
        return self.start_model_task(question, question, action, 'Project task; see the result and checkpoints.', keep_alive=keep_alive)

    def add_game_card(self, game, index):
        super().add_game_card(game, index)
        if game['built_in']: return
        card = self.game_cards.grid_slaves(row=index // 2, column=index % 2)[0]
        tools = tk.Frame(card, bg=self.colors['panel'])
        tools.grid(row=5, column=0, columnspan=3, sticky='ew', padx=12, pady=(0, 11))
        self.small_button(tools, 'Edit in chat', lambda: self.open_game_chat(game['script'])).grid(row=0,column=0,sticky='w')
        self.small_button(tools, 'Fix & retest', lambda: self.fix_game(game['script'])).grid(row=0,column=1,sticky='w',padx=4)
        self.small_button(tools, 'History', lambda: self.show_project_history(game['script'])).grid(row=1,column=0,sticky='w')
        if not game['script'].is_file():
            for frame in card.grid_slaves(row=4):
                for child in frame.winfo_children(): child.configure(state='disabled')

    def game_card_menu(self, game, button):
        menu = tk.Menu(self.root, tearoff=0)
        script = game['script']
        actions = [('★ Favorite' if not game['favorite'] else 'Remove favorite', lambda: self.toggle_game_favorite(game))]
        if not game['built_in']:
            actions += [('Edit in chat', lambda: self.open_game_chat(script)), ('Fix & retest', lambda: self.fix_game(script)),
                        ('Resume build', lambda: self.resume_game(script)), ('History / Undo', lambda: self.show_project_history(script)),
                        ('Shared module contracts', lambda: self.show_contracts(script)), ('Check dependency compatibility', lambda: self.check_game_dependencies(script)),
                        ('Export playable demo', lambda: self.export_game(script))]
        actions += [('Install dependencies', lambda: self.show_dependencies(script)),
                    ('Rename game', lambda: self.edit_game_metadata(game)), ('Choose cover image', lambda: self.edit_game_metadata(game, cover=True)),
                    ('View code', lambda: self.show_file_preview(script)), ('Open folder', lambda: self.open_path(script.parent))]
        for label, action in actions: menu.add_command(label=label, command=action)
        if game['test_report']: menu.add_command(label='Last test report', command=lambda: self.show_file_preview(game['test_report']))
        if not game['built_in']:
            menu.add_separator()
            menu.add_command(label='Delete game', command=lambda: self.delete_game(game))
        self._game_menu = menu
        try: menu.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())
        finally: menu.grab_release()

    def add_message_actions(self, content):
        super().add_message_actions(content)
        script = game_from_message(self._root(), content)
        if script:
            row = tk.Frame(self.view, bg=self.colors['bg'])
            for label, action in [('Edit game', lambda: self.open_game_chat(script)), ('Fix & retest', lambda: self.fix_game(script)),
                                  ('Resume', lambda: self.resume_game(script)), ('Undo / History', lambda: self.show_project_history(script))]:
                self.small_button(row, label, action).pack(side='left', padx=3, pady=3)
            self.view.window_create('end', window=row, padx=2, pady=3)
            self.view.insert('end', '\n')
            self.message_buttons.append(row)

    def resume_game(self, script):
        from agent import resume_project
        self._start_game_action(script, 'Resume build: ' + script.parent.name,
                                lambda progress: resume_project(script, progress, self.build_cancelled))

    def fix_game(self, script):
        if self.busy:
            self.set_status('Finish the current task first.')
            return
        if not Path(script).is_file():
            return self.resume_game(script)
        script = self.approved_game_path(script, test=True)
        if script is None or not self.dependencies_ready(script): return
        def action(progress):
            from agent import edit_project
            from game_tester import run_game_test
            if game_info(script)['test_status'] in {'untested','stale','incomplete'}:
                result = run_game_test(script, progress, self.test_cancelled)
                if game_info(script)['test_status'] == 'passed': return result + '\nNo failing check requires a fix.'
            if self.build_cancelled.is_set(): return 'Fix task paused.'
            return edit_project(script, 'Fix the actual failed checks and traceback in the latest report, then retest. '
                                'Preserve gameplay and public interfaces.', progress, repair=True, cancelled=self.build_cancelled)
        self._start_game_action(script, 'Fix and retest: ' + script.parent.name, action)

    def finish_reply(self, chat_id, question, answer, summary, title_role):
        if question.startswith(('/build', '/edit', '/fix', '/resume', 'Create ')):
            script = game_from_message(self._root(), answer)
            if script:
                with self._host().connect() as db:
                    db.execute('INSERT OR REPLACE INTO chat_games(chat_id,script) VALUES(?,?)', (chat_id,str(script)))
        return super().finish_reply(chat_id, question, answer, summary, title_role)

    def set_status(self, text):
        super().set_status(text)
        if getattr(self, 'chat_id', None) is not None:
            self.editing_game = self._chat_script(self.chat_id)
            self.update_studio_context()

    def test_game(self, script):
        if os.name == 'nt' or not (Path(script).parent / 'game_core.py').is_file():
            self.test_cancelled.clear()
            return super().test_game(script)
        script = self.approved_game_path(script, test=True)
        if script is None: return False
        from game_tester import run_game_test
        return self._start_game_action(script, 'Test game: ' + script.parent.name,
                                       lambda progress: run_game_test(script, progress, self.test_cancelled))

    def show_project_history(self, script):
        project = Path(script).parent
        win = tk.Toplevel(self.root)
        win.title('Project history — ' + game_info(script)['title'])
        win.geometry('760x540')
        win.configure(bg=self.colors['bg'])
        tk.Label(win, text='Undo AI changes', bg=self.colors['bg'], fg=self.colors['fg'], font=(self.font, 16, 'bold')).pack(anchor='w', padx=20, pady=16)
        listing = tk.Listbox(win, bg=self.colors['panel'], fg=self.colors['fg'], exportselection=False)
        listing.pack(fill='both', expand=True, padx=20)
        selected = tk.StringVar(value='All files')
        files = ttk.Combobox(win, textvariable=selected, state='readonly')
        files.pack(fill='x', padx=20, pady=12)
        items = []
        def choose(_event=None):
            indexes = listing.curselection()
            names = sorted(items[indexes[0]]['files']) if indexes and indexes[0] < len(items) else []
            files.configure(values=['All files', *names])
            selected.set('All files')
        def reload():
            items[:] = checkpoints(project)
            listing.delete(0, 'end')
            for item in items:
                when = time.strftime('%m-%d %H:%M:%S', time.localtime(item['time']))
                listing.insert('end', when + ' · ' + item.get('label', item['id']))
            if items: listing.selection_set(0)
            else: listing.insert('end', 'No checkpoints yet. AI edits create them automatically.')
            choose()
        def undo():
            if self.busy:
                self.set_status('Finish the current task before undoing source changes.')
                return
            indexes = listing.curselection()
            if not indexes or indexes[0] >= len(items): return
            try:
                restore_checkpoint(project, items[indexes[0]]['id'], None if selected.get() == 'All files' else [selected.get()])
                reload()
                if self.current_page == 'games': self.draw_game_cards()
                self.set_status('Checkpoint restored. The previous state was saved as another checkpoint.')
            except (ValueError, OSError) as error: messagebox.showerror('Undo', str(error), parent=win)
        listing.bind('<<ListboxSelect>>', choose)
        self.primary_button(win, 'Restore selected checkpoint / file', undo).pack(anchor='w', padx=20, pady=(0,18))
        reload()

    def show_contracts(self, script):
        path = Path(script).parent / 'contracts.json'
        if not path.exists():
            atomic_json(path, {'version': 1, 'modules': {name: extract_api(source) for name, source in sources(path.parent).items() if name.endswith('.py')}})
        self.show_file_preview(path)

    def check_game_dependencies(self, script):
        def action(progress):
            data = check_dependencies(script, progress)
            return ('Project saved: ' + str(Path(script).parent.relative_to(self._root())) + '\nDependency compatibility: ' +
                    ('READY' if data['ready'] else 'NEEDS ATTENTION') + '\n' + '\n'.join(data.get('notices', [])) + '\n' + data['log'])
        self._start_game_action(script, 'Check dependency compatibility: ' + Path(script).parent.name, action)

    def export_game(self, script):
        if not Path(script).is_file():
            messagebox.showinfo('Export demo', 'Resume this build to create its entry point before exporting a playable demo.', parent=self.root)
            return
        project = Path(script).parent
        compatible = all((project / name).exists() and (project / name).read_bytes() == (self._root() / original).read_bytes()
                         for name, original in [('game_core.py','template_core.py'),('game_view.py','template_view.py')])
        suffix = '.html' if compatible else '.zip'
        path = filedialog.asksaveasfilename(parent=self.root, title='Export playable demo', defaultextension=suffix,
            initialfile='game-demo' + suffix, filetypes=[('Offline HTML demo', '*.html'), ('Python source demo', '*.zip')])
        if not path: return
        try:
            result = export_demo(script, path, format='html' if Path(path).suffix.lower() == '.html' else 'zip')
            messagebox.showinfo('Demo exported', result['path'] + '\n\n' + result['note'], parent=self.root)
        except (OSError, ValueError) as error: messagebox.showerror('Export demo', str(error), parent=self.root)

    def show_template_picker(self):
        win = tk.Toplevel(self.root)
        win.title('Brain AI — Game foundations')
        win.geometry('700x540')
        win.configure(bg=self.colors['bg'])
        tk.Label(win, text='Start from a playable foundation', bg=self.colors['bg'], fg=self.colors['fg'], font=(self.font,16,'bold')).pack(anchor='w',padx=22,pady=20)
        kind = tk.StringVar(value='platformer')
        for key, config in TEMPLATES.items():
            tk.Radiobutton(win,text=config['title'] + ' — ' + config['description'], variable=kind, value=key,
                bg=self.colors['bg'],fg=self.colors['fg'],selectcolor=self.colors['field'],wraplength=620,anchor='w').pack(fill='x',padx=22,pady=8)
        tk.Label(win,text='Optional AI request:',bg=self.colors['bg'],fg=self.colors['muted']).pack(anchor='w',padx=22,pady=(15,5))
        entry = tk.Text(win,height=4,bg=self.colors['field'],fg=self.colors['fg'],insertbackground=self.colors['fg'],wrap='word')
        entry.pack(fill='x',padx=22)
        def start(ai):
            selected, task = kind.get(), entry.get('1.0','end').strip()
            if ai and not task:
                messagebox.showinfo('Game request','Describe what you want to change.',parent=win)
                return
            self.build_cancelled.clear()
            def action(progress):
                if ai:
                    from agent import build
                    return build(task, progress, template=selected, cancelled=self.build_cancelled)
                folder = self._root() / 'workspace' / (selected + '-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:4])
                script = seed_template(folder, selected)
                from gameplay_checks import run_checks
                result = run_checks(script, progress)
                atomic_json(folder / 'build_report.json', {'task': TEMPLATES[selected]['description'], 'generated_files': list(sources(folder)),
                            'errors': [], 'code_executed': True, 'template': selected})
                return f'Project saved: {folder.relative_to(self._root())}\nFoundation: {selected}\nGameplay checks: {result["status"]}\nEdit the game through its Edit in chat button.'
            if self._start_game_action(None, 'Create ' + selected + (' with AI' if ai else ' foundation'), action): win.destroy()
        buttons = tk.Frame(win,bg=self.colors['bg'])
        buttons.pack(fill='x',padx=22,pady=18)
        self.primary_button(buttons,'Create playable template',lambda:start(False)).pack(side='left')
        self.small_button(buttons,'Customize with AI',lambda:start(True)).pack(side='left',padx=10)

    def show_agent_dashboard(self):
        win = tk.Toplevel(self.root)
        win.title('Brain AI — Agent dashboard')
        win.geometry('740x640')
        win.configure(bg=self.colors['bg'])
        tk.Label(win,text='Agent dashboard',bg=self.colors['bg'],fg=self.colors['fg'],font=(self.font,18,'bold')).pack(anchor='w',padx=22,pady=20)
        labels = {}
        for key in ['Model / last request','Role','State','Task','Request elapsed','Last completion tokens','Last tokens / sec','System RAM','Model process RAM','Last error']:
            row=tk.Frame(win,bg=self.colors['bg']);row.pack(fill='x',padx=22,pady=5)
            tk.Label(row,text=key,bg=self.colors['bg'],fg=self.colors['muted'],width=24,anchor='w').pack(side='left')
            labels[key]=tk.Label(row,bg=self.colors['bg'],fg=self.colors['fg'],anchor='w',justify='left',wraplength=400)
            labels[key].pack(side='left',fill='x',expand=True)
        def gb(value): return f'{value/1024**3:.2f} GB' if value is not None else 'Unavailable'
        def refresh():
            if not win.winfo_exists(): return
            data=runtime.metrics() if hasattr(runtime,'metrics') else {}
            memory=memory_usage(data.get('process_pid'))
            total,available=memory['total_bytes'],memory['available_bytes']
            values={'Model / last request':data.get('model') or 'No request yet','Role':data.get('role') or '—',
                    'State':data.get('state','idle'),'Task':data.get('task','Ready'),
                    'Request elapsed':f'{data["elapsed"]:.1f}s' if data.get('elapsed') is not None else '—',
                    'Last completion tokens':data.get('completion_tokens',0),
                    'Last tokens / sec':f'{data["tokens_per_second"]:.2f}' if data.get('tokens_per_second') is not None else '—',
                    'System RAM':gb(total-available)+' / '+gb(total) if total is not None and available is not None else 'Unavailable',
                    'Model process RAM':gb(memory['process_bytes']),'Last error':str(data.get('last_error') or '—')[:300]}
            for key,value in values.items(): labels[key].configure(text=str(value))
            win.after(1000,refresh)
        refresh()

    def close_app(self):
        self.build_cancelled.set()
        super().close_app()

    def show_features(self):
        self.show_file_preview(self._root() / 'BrainAI_Studio_Guide.md')
