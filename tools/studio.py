"""Build a local video from a prompt in a single Windows workspace."""

from datetime import datetime
import json
import os
from pathlib import Path
from queue import Empty, Queue
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from uuid import uuid4

from dialogue_request import cast_for, wants_dialogue
from local_scene_planner import MAX_REQUEST_LENGTH, SCENE_LABEL
from render_storage import file_lock
from scene_request_3d import CREATE, normalize
from scene_revision import write_json
from setup_studio import prepare_dialogue
from studio_references import EXTENSIONS, MAX_FILES, prepare_references


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / 'out/studio'
ICON = ROOT / 'tools/admiral8.ico'
BACKGROUND = '#101722'
SURFACE = '#182332'
BORDER = '#32435b'
TEXT = '#f2f5fa'
MUTED = '#aebcd0'
ACCENT = '#8be0cf'
BUILD_STAGES = {'Синтез голосов героев': 'Озвучиваем реплики…',
                'Подготовка сцены, мимики и камер': 'Собираем сцену и камеры…',
                'Проверка и рендер кадров': 'Рендерим кадры…',
                'Проверка и экспорт MP4': 'Собираем MP4…'}


def planner_paths(workspace):
    resources = workspace / 'resources'
    defaults = (resources / 'runtime/bin/llama-server.exe', resources / 'model/qwen.gguf')
    try:
        settings = json.loads((workspace / 'settings.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        settings = {}
    if not isinstance(settings, dict):
        settings = {}
    paths = []
    for key, default in zip(('runtime', 'model'), defaults):
        saved = settings.get(key)
        paths.append(Path(saved) if not default.is_file() and isinstance(saved, str) else default)
    return paths


def job_command(request, out, workspace, reference=None):
    python = Path(sys.executable)
    if python.name.lower() == 'pythonw.exe':
        python = python.with_name('python.exe')
    start = [str(python), '-X', 'utf8']
    options = ['--request', request, '--out', str(out)]
    args = [*start, str(ROOT / 'tools/quickstart.py'), '3d', *options]
    if CREATE.fullmatch(normalize(request)) and not reference:
        return args, out / 'draft/preview.mp4'
    runtime, model = planner_paths(workspace)
    if not runtime.is_file() or not model.is_file():
        raise ValueError('Локальная модель не установлена. Откройте инструкцию по настройке.')
    if wants_dialogue(request):
        writer = workspace / 'resources/model/dialogue.gguf'
        if writer.is_file():
            model = writer
        args = [*start, str(ROOT / 'tools/dialogue_request.py'), *options,
                '--runtime', str(runtime), '--model', str(model)]
        if reference:
            args.extend(['--reference-look', str(reference)])
        return args, out / 'draft/preview.mp4'
    profile = 'sequence' if SCENE_LABEL.search(request) else 'objects'
    args.extend(['--planner', profile, '--runtime', str(runtime), '--model', str(model)])
    if reference:
        args.extend(['--reference-look', str(reference)])
    relative = 'scene/preview.mp4' if profile == 'sequence' else 'scene/draft/preview.mp4'
    return args, out / relative


class Studio:
    def __init__(self, window, workspace=WORKSPACE):
        self.window = window
        self.workspace = workspace
        self.events = Queue()
        self.busy = False
        self.attachments = []
        self.pasted = None
        self.status = tk.StringVar(master=window, value='Готово к работе')
        self.build()
        window.after(100, self.poll)
        window.bind('<Control-Return>', self.start)
        window.protocol('WM_DELETE_WINDOW', self.close)

    def build(self):
        self.window.title('Admiral8 Renders')
        self.window.configure(bg=BACKGROUND)
        self.window.geometry('800x550')
        self.window.minsize(615, 505)
        if os.name == 'nt':
            self.window.iconbitmap(default=str(ICON))

        style = ttk.Style(self.window)
        style.theme_use('clam')
        style.configure('Action.TButton', font=('Segoe UI', 11, 'bold'), padding=(18, 10),
                        background=ACCENT, foreground=BACKGROUND, borderwidth=0)
        style.map('Action.TButton', background=[('disabled', BORDER), ('pressed', '#64bdad'),
                                                 ('active', '#a4ecdf')],
                  foreground=[('disabled', MUTED)])
        style.configure('Link.TButton', font=('Segoe UI', 10), padding=(5, 5),
                        background=BACKGROUND, foreground=ACCENT, borderwidth=0)
        style.map('Link.TButton', background=[('active', SURFACE)], foreground=[('disabled', MUTED)])
        style.configure('Studio.Horizontal.TProgressbar', background=ACCENT, troughcolor=BORDER,
                        bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT, thickness=4)

        page = tk.Frame(self.window, bg=BACKGROUND, padx=34, pady=25)
        page.pack(fill='both', expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(4, weight=1)

        tk.Label(page, text='ADMIRAL8 RENDERS', bg=BACKGROUND, fg=ACCENT,
                 font=('Segoe UI', 10, 'bold')).grid(row=0, sticky='w')
        tk.Label(page, text='Создать видео', bg=BACKGROUND, fg=TEXT,
                 font=('Segoe UI', 30, 'bold')).grid(row=1, sticky='w', pady=(4, 2))
        tk.Label(page, text='Опишите, что должно быть в кадре, как это движется и сколько длится.',
                 bg=BACKGROUND, fg=MUTED, font=('Segoe UI', 11)).grid(row=2, sticky='w')

        prompt_header = tk.Frame(page, bg=BACKGROUND)
        prompt_header.grid(row=3, sticky='ew', pady=(19, 4))
        tk.Label(prompt_header, text='Промпт', bg=BACKGROUND, fg=TEXT,
                 font=('Segoe UI', 11, 'bold')).pack(side='left')
        self.attach_button = ttk.Button(prompt_header, text='Прикрепить', style='Link.TButton',
                                        command=self.choose_files)
        self.attach_button.pack(side='right')

        self.prompt = tk.Text(page, height=4, wrap='word', undo=True, bg=SURFACE, fg=TEXT,
                              insertbackground=TEXT, selectbackground='#345c68',
                              font=('Segoe UI', 13), padx=15, pady=12, relief='flat', borderwidth=0,
                              highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
        self.prompt.grid(row=4, sticky='nsew')
        self.prompt.bind('<Control-Return>', self.start)
        self.prompt.bind('<Tab>', self.focus_next)
        self.prompt.bind('<<Paste>>', self.paste_reference)
        self.prompt.focus_set()
        self.file_list = tk.Frame(page, bg=BACKGROUND)
        self.file_list.grid(row=5, sticky='ew', pady=(5, 12))
        self.show_files()

        actions = tk.Frame(page, bg=BACKGROUND)
        actions.grid(row=6, sticky='ew')
        self.run_button = ttk.Button(actions, text='Собрать видео', style='Action.TButton', command=self.start)
        self.run_button.pack(side='left')
        tk.Label(actions, text='Ctrl+Enter', bg=BACKGROUND, fg=MUTED,
                 font=('Segoe UI', 9)).pack(side='left', padx=12)
        self.result_button = ttk.Button(actions, style='Link.TButton')
        self.progress = ttk.Progressbar(page, style='Studio.Horizontal.TProgressbar', mode='indeterminate')
        self.progress.grid(row=7, sticky='ew', pady=(13, 5))
        self.progress.grid_remove()
        self.status_label = tk.Label(page, textvariable=self.status, bg=BACKGROUND, fg=MUTED,
                                     anchor='w', justify='left', font=('Segoe UI', 10))
        self.status_label.grid(row=8, sticky='ew', pady=(9, 0))
        page.bind('<Configure>', lambda event: self.status_label.configure(wraplength=max(1, event.width - 68)))

    def show_files(self):
        for widget in self.file_list.winfo_children():
            widget.destroy()
        if not self.attachments:
            tk.Label(self.file_list, text='Можно прикрепить фото, видео или текст.',
                     bg=BACKGROUND, fg=MUTED, font=('Segoe UI', 10)).pack(anchor='w')
        for path in self.attachments:
            row = tk.Frame(self.file_list, bg=BACKGROUND)
            row.pack(fill='x')
            label = path.name if len(path.name) <= 58 else path.name[:45] + '…' + path.suffix
            ttk.Button(row, text=label, style='Link.TButton',
                       command=lambda file=path: self.open_path(file)).pack(side='left')
            ttk.Button(row, text='×', style='Link.TButton', width=3,
                       state='disabled' if self.busy else 'normal',
                       command=lambda file=path: self.remove_reference(file)).pack(side='left')

    def add_references(self, paths):
        items = [path for path in dict.fromkeys(paths) if path not in self.attachments]
        if any(path.suffix.lower() not in EXTENSIONS for path in items):
            self.status.set('Прикрепите изображение, видео, TXT или Markdown.')
        elif len(items) + len(self.attachments) > MAX_FILES:
            self.status.set(f'Можно прикрепить до {MAX_FILES} файлов.')
        else:
            self.attachments.extend(items)
            self.status.set('Готово к работе')
            self.show_files()

    def remove_reference(self, path):
        self.attachments.remove(path)
        self.show_files()

    def choose_files(self):
        pattern = ' '.join(f'*{ext}' for ext in sorted(EXTENSIONS))
        selected = filedialog.askopenfilenames(parent=self.window, title='Прикрепить референсы',
                                               filetypes=[('Референсы', pattern)])
        if selected:
            self.add_references(map(Path, selected))

    def paste_reference(self, _event):
        from PIL import Image, ImageGrab

        if self.busy:
            return 'break'
        try:
            item = ImageGrab.grabclipboard()
        except OSError:
            return None
        if isinstance(item, list):
            self.add_references(map(Path, item))
            return 'break'
        if isinstance(item, Image.Image):
            if len(self.attachments) < MAX_FILES:
                if self.pasted is None:
                    self.pasted = TemporaryDirectory(prefix='admiral8-reference-')
                path = Path(self.pasted.name) / f'Из буфера {uuid4().hex[:6]}.png'
                item.save(path)
                self.add_references([path])
            else:
                self.status.set(f'Можно прикрепить до {MAX_FILES} файлов.')
            return 'break'
        return None

    def focus_next(self, _event):
        self.prompt.tk_focusNext().focus_set()
        return 'break'

    def show_action(self, label, path):
        self.result_button.configure(text=label, command=lambda: self.open_path(path))
        self.result_button.pack(side='right')

    def start(self, _event=None):
        if self.busy:
            return 'break'
        request = self.prompt.get('1.0', 'end-1c').strip()
        if not request or len(request) > MAX_REQUEST_LENGTH:
            self.status.set('Опишите ролик.' if not request
                            else f'Сократите описание до {MAX_REQUEST_LENGTH} символов.')
            self.prompt.focus_set()
            return 'break'
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        out = self.workspace / f'{stamp}-{uuid4().hex[:6]}'
        self.busy = True
        self.result_button.pack_forget()
        self.prompt.configure(state='disabled')
        self.attach_button.configure(state='disabled')
        self.show_files()
        self.run_button.configure(state='disabled')
        self.status.set('Собираем видео…')
        self.progress.grid()
        self.progress.start(14)
        Thread(target=self.worker, args=(request, out, tuple(self.attachments)), daemon=True).start()
        return 'break'

    def worker(self, request, out, attachments):
        log_path = out.with_suffix('.log')
        try:
            with file_lock(self.workspace / 'studio.lock'), log_path.open('w', encoding='utf-8') as log, \
                    TemporaryDirectory(prefix='.reference-', dir=self.workspace) as temp:
                reference, snapshot = None, Path(temp) / 'references'
                if attachments:
                    texts, profile = prepare_references(snapshot, attachments)
                    request = '\n\n'.join([request, *filter(None, texts)])
                    if len(request) > MAX_REQUEST_LENGTH:
                        raise ValueError(f'Промпт и текстовые референсы вместе должны быть до {MAX_REQUEST_LENGTH} символов.')
                    write_json(snapshot / 'look.json', profile)
                    if profile.get('palette'):
                        reference = snapshot / 'look.json'
                env = dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1')
                if wants_dialogue(request):
                    if set(cast_for(request)) != {'pudge', 'invoker'}:
                        raise ValueError('Для диалога сейчас доступны Пудж и Инвокер. Укажите обоих героев.')
                    python = Path(sys.executable).with_name('python.exe')
                    env.update(prepare_dialogue(python, lambda stage: self.events.put(('progress', stage, None)), log))
                args, movie = job_command(request, out, self.workspace, reference)
                with subprocess.Popen(args, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, encoding='utf-8', errors='replace',
                                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as child:
                    explanation = None
                    prefixes = ('Локальная сборка не завершена. ', 'Быстрый запуск не завершён. ')
                    for line in child.stdout:
                        log.write(line)
                        log.flush()
                        if stage := BUILD_STAGES.get(line.strip()):
                            self.events.put(('progress', stage, None))
                        if line.startswith(prefixes):
                            explanation = line.strip().split('. ', 1)[1]
                    result = child.wait()
                if snapshot.is_dir() and out.is_dir():
                    shutil.move(snapshot, out / 'references')
            if result or not movie.is_file():
                generic = 'Не удалось собрать видео. Подробности в журнале.'
                message = explanation if explanation and len(explanation) <= 180 else generic
                self.events.put(('error', message, log_path))
            else:
                self.events.put(('done', 'Видео готово', movie))
        except ValueError as error:
            message = str(error)
            path = ROOT / 'docs/SETUP.md' if 'по настройке' in message else None
            self.events.put(('setup' if path else 'error', message, path))
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            message = ('Уже идёт другая сборка. Дождитесь её завершения.'
                       if str(error).startswith('File lock unavailable:')
                       else f'Не удалось запустить сборку. {error}')
            self.events.put(('error', message, log_path))

    def poll(self):
        try:
            event, message, path = self.events.get_nowait()
        except Empty:
            pass
        else:
            if event == 'progress':
                self.status.set(message)
                self.window.after(100, self.poll)
                return
            self.busy = False
            self.progress.stop()
            self.progress.grid_remove()
            self.prompt.configure(state='normal')
            self.attach_button.configure(state='normal')
            self.show_files()
            self.run_button.configure(state='normal')
            self.status.set(message)
            if event == 'done':
                self.show_action('Открыть видео', path)
            elif event == 'setup':
                self.show_action('Настройка', path)
            elif path and path.is_file():
                self.show_action('Журнал', path)
        self.window.after(100, self.poll)

    def open_path(self, path):
        try:
            os.startfile(path)
        except (AttributeError, OSError) as error:
            self.status.set(str(error))

    def close(self):
        if self.busy:
            messagebox.showinfo('Admiral8 Renders', 'Дождитесь завершения текущей сборки.', parent=self.window)
        else:
            if self.pasted is not None:
                self.pasted.cleanup()
            self.window.destroy()


if __name__ == '__main__':
    window = tk.Tk()
    Studio(window)
    window.mainloop()
