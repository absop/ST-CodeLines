import re
import os
import time
import threading
from contextlib import contextmanager
from functools import partial, reduce
from os.path import relpath

import sublime
import sublime_plugin

from .lib import lc
from .lib import utils
from .lib.utils import cd, strsize, try_or_zero


def debug(*args):
    if debug._debug:
        print(f'{__package__}:', *args)

debug._debug = False
error = sublime.error_message


def walk_exclude_hidden(top):
    return os.walk(top)


class SideBarFileSizeCommand(sublime_plugin.WindowCommand):
    command = 'code_lines_file_size'

    def run(self, paths, **args):
        args.update({'path': paths[0]})
        self.window.run_command(self.command, args)

    def is_visible(self, paths, **args):
        return len(paths) == 1 and os.path.exists(paths[0])


class SideBarCodeLinesCommand(SideBarFileSizeCommand):
    command = 'code_lines_in_directory'


class SideBarCodeLinesWithPatternCommand(SideBarFileSizeCommand):
    command = 'code_lines_in_directory_with_pattern'

    def is_visible(self, paths, **args):
        return len(paths) == 1 and os.path.isdir(paths[0])


class CodeLinesShowTypesCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        if self.view.settings().has("cl_languages"):
            pt = self.view.sel()[0].a
            CodeLinesViewsManager.show_types_at(self.view, pt)


class CodeLinesOpenFileCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        if self.view.settings().has("cl_language"):
            pt = self.view.sel()[0].a
            CodeLinesViewsManager.open_file_at(self.view, pt)


class CodeLinesToggleLogCommand(sublime_plugin.WindowCommand):
    def run(self):
        debug._debug = not debug._debug


class PathInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, is_wanted=os.path.exists, path_type='File Path'):
        self.is_wanted = is_wanted
        self.path_type = path_type

    def placeholder(self):
        return self.path_type

    def initial_text(self):
        view = sublime.active_window().active_view()
        if view:
            path = view.file_name()
            if path and os.path.exists(path):
                return path
        return ''

    def validate(self, path):
        return self.is_wanted(path)


class CodeLinesFileSizeCommand(sublime_plugin.WindowCommand):
    def run(self, path):
        task = StatusBarTask(lambda: self.show_size(path),
            'Counting...', 'Succeed.')
        StatusBarThread(task, self.window, __package__)

    def input(self, args):
        return PathInputHandler()

    def show_size(self, path):
        def strsize(bytes):
            return f'{utils.strsize(bytes)}({bytes} Bytes)'

        if os.path.isfile(path):
            output = (
                f'PATH: {path}\n'
                f'Size: {strsize(os.path.getsize(path))}')
        else:
            info = self.FolderInfo(path)
            output = (
                f'ROOTDIR: {path}\n'
                f'TotalSize:\t{strsize(info.size)}\n'
                f'Contains:\tFiles: {info.files}, Folders: {info.folders}')

        panel = self.window.create_output_panel('FileSize')
        panel.assign_syntax('FileSize.sublime-syntax')
        panel.run_command('append', {'characters': output})
        self.window.run_command('show_panel', {'panel': 'output.FileSize'})

    class FolderInfo:
        __slots__ = ['size', 'files', 'folders']

        def __init__(self, path):
            self.size = 0
            self.files = 0
            self.folders = 0
            for path, dirs, files in os.walk(path):
                for file in files:
                    self.size += os.path.getsize(os.path.join(path, file))
                self.files += len(files)
                self.folders += len(dirs)


class CodeLinesInDefaultPathCommand(sublime_plugin.WindowCommand):
    def run(self):
        self.window.run_command(
            'code_lines_in_directory_with_pattern',
            {
                'path': CodeLinesViewsManager.default_path,
                'from_settings': True
            })


class CodeLinesInDirectoryCommand(sublime_plugin.WindowCommand):
    def run(self, path, **args):
        if os.path.isdir(path):
            self.count_directory(path, **args)
        elif os.path.isfile(path):
            self.count_singel_file(path)
        else:
            error(f'CodeLines: No such file or directory: {path}')

    def input(self, path, **args):
        return PathInputHandler()

    def count_singel_file(self, path):
        message = f'The file {path} has {lc.count(path)} lines'
        sublime.message_dialog(message)

    def count_directory(self, path):
        CodeLinesViewsManager.run_task(self.window, path, self.get_filepaths)

    def get_filepaths(self, walk_result):
        filepaths = []
        for root, _, files in walk_result:
            for file in files:
                path = os.path.join(root, file)
                filepaths.append((path, file))
        return filepaths


class CodeLinesInDirectoryWithPatternCommand(CodeLinesInDirectoryCommand):
    def input(self, path, **args):
        return PathInputHandler(
            is_wanted=os.path.isdir,
            path_type='Directory Path')

    def count_directory(self, path, from_settings=True):
        def count_directory_with_pattern(path, pattern):
            debug(f'pattern: {pattern}')
            self.regex = re.compile(pattern)
            super(self.__class__, self).count_directory(path)

        default_pattern = CodeLinesViewsManager.default_pattern
        if from_settings:
            count_directory_with_pattern(path, default_pattern)
        else:
            panel = self.window.show_input_panel(
                'Path Regexp', default_pattern,
                partial(count_directory_with_pattern, path),
                None, None)
            panel.sel().clear()
            panel.sel().add(sublime.Region(0, len(default_pattern)))
            panel.assign_syntax('RegExp.sublime-syntax')

    def get_filepaths(self, walk_result):
        filepaths = []
        for root, _, files in walk_result:
            for file in files:
                path = os.path.join(root, file)
                if self.regex.fullmatch(path):
                    filepaths.append((path, file))
        return filepaths


class CodeLinesViewsManager(sublime_plugin.EventListener):
    syntax_path = f'{__package__}.sublime-syntax'
    settings_name = f'{__package__}.sublime-settings'

    @classmethod
    def setup(cls):
        settings = sublime.load_settings(cls.settings_name)
        settings.clear_on_change('encoding')
        settings.add_on_change('encoding', lambda: cls.load(settings))
        cls.load(settings)
        lc.load_binary()

    @classmethod
    def exit(cls):
        lc.unload_binary()

    @classmethod
    def load(cls, settings):
        lc.set_encoding(settings.get('encoding', 'utf-8'))
        cls.font_face = settings.get('font_face', 'Lucida Console')
        cls.default_path = settings.get('default_path', '')
        cls.default_pattern = settings.get('default_pattern', '.*')
        syntaxes = settings.get('syntaxes', [])
        ignored_syntaxes = settings.get('ignored_syntaxes', [])
        aliases_ = settings.get('aliases', {})
        aliases = {}
        for syntax in aliases_:
            for aliase in aliases_[syntax]:
                aliases[aliase] = syntax
        cls.language_decider = cls.create_language_decider(
            syntaxes, ignored_syntaxes, aliases)
        if settings.get('exclude_hidden_files', True):
            cls.walk = walk_exclude_hidden
        else:
            cls.walk = os.walk

    @classmethod
    def create_language_decider(cls, syntaxes, ignored_syntaxes, aliases):
        if syntaxes:
            def get_language_with_syntaxes(file):
                lang = sublime.find_syntax_for_file(file).name
                if lang in aliases:
                    lang = aliases[lang]
                if lang in syntaxes:
                    return lang
                return None
            return get_language_with_syntaxes
        else:
            def get_language_with_ignored_syntaxes(file):
                lang = sublime.find_syntax_for_file(file).name
                if lang in ignored_syntaxes:
                    return None
                if lang in aliases:
                    lang = aliases[lang]
                    if lang in ignored_syntaxes:
                        return None
                return lang
            return get_language_with_ignored_syntaxes

    @classmethod
    def run_task(cls, window, rootdir, get_filepaths):
        cl_time = time.strftime("%Y/%m/%d/%H:%M")
        compose = lambda fs: reduce(lambda f, g: lambda x: f(g(x)), fs)
        task = StatusBarTask(None, 'Counting files', 'Succeed')
        task.function = lambda: compose([
            partial(cls.show_languages, window, rootdir, cl_time),
            partial(cls.count_lines, task, rootdir),
            get_filepaths,
            cls.walk
        ])(rootdir)
        StatusBarThread(task, window, __package__)

    @classmethod
    def count_lines(cls, task, rootdir, filepaths):
        task.message = 'Counting lines'
        status_message = task.status_message
        show_status_message = task.status_bar.show_status_message
        decide_language = cls.language_decider
        languages = Languages()
        counted, total = 0, len(filepaths)
        with task.status_bar.pause():
            for path, file in filepaths:
                lang = decide_language(file)
                if lang:
                    ext = os.path.splitext(file)[1].lstrip('.')
                    type = ext if ext else file
                    languages.insert(lang, type, path)
                counted += 1
                show_status_message(f'{status_message()}({counted}/{total})')
        languages.summarize()
        return languages

    @classmethod
    def show_languages(cls, window, rootdir, cl_time, languages):
        if not languages.entries:
            window.status_message(f'{__package__}: No matching files')
            return
        cl_languages = {}
        with cd(rootdir):
            for lang, types in languages.entries.items():
                cl_languages[lang] = types.report()
        head = f'ROOTDIR: {rootdir}\nTime: {cl_time}\n\n\n'
        body = languages.report()
        cls.create_view(
            window,
            settings={
                'rootdir': rootdir,
                'cl_time': cl_time,
                'cl_languages': cl_languages
            },
            text=head + body)

    @classmethod
    def show_types(cls, view, rootdir, cl_time, lang, types_report):
        debug(f'open language {lang}')
        head = f'ROOTDIR: {rootdir}\nTime: {cl_time}\n\n\n'
        body = types_report
        cls.create_view(
            view.window(),
            settings={
                'rootdir': rootdir,
                'cl_time': cl_time,
                'cl_language': lang,
            },
            text=head + body,
            name=f'{__package__} - {lang}')

    @classmethod
    def create_view(cls, window, settings={}, text='', name=__package__):
        settings.update({
            'font_face': cls.font_face,
            'word_wrap': False,
            'translate_tabs_to_spaces': True
            })
        view = window.new_file()
        view.settings().update(settings)
        view.assign_syntax(cls.syntax_path)
        view.run_command("append", {"characters": text})
        view.set_name(name)
        view.set_scratch(True)
        view.set_read_only(True)

    @classmethod
    def show_types_at(cls, view, pt):
        cl_languages = view.settings().get("cl_languages")
        lang = view.substr(view.extract_scope(pt))
        if lang in cl_languages:
            rootdir = view.settings().get("rootdir")
            cl_time = view.settings().get("cl_time")
            cls.show_types(view, rootdir, cl_time, lang, cl_languages[lang])
            return True
        return False

    @classmethod
    def open_file_at(cls, view, pt):
        rootdir = view.settings().get("rootdir")
        relpath = view.substr(view.extract_scope(pt))
        abspath = os.path.join(rootdir, relpath)
        if os.path.isfile(abspath):
            debug(f'open source file {abspath}')
            view.window().open_file(abspath, sublime.ENCODED_POSITION)
            return True
        return False

    def on_text_command(self, view, name, args):
        # print(name, args)
        # Affected by `Chinese Words Cutter`
        if name == "drag_select" and args.get("by", "") == "words":
            event = args["event"]
            pt = view.window_to_text((event["x"], event["y"]))
            if view.settings().has("cl_language"):
                if CodeLinesViewsManager.open_file_at(view, pt):
                    return (name, args)
            elif view.settings().has("cl_languages"):
                if CodeLinesViewsManager.show_types_at(view, pt):
                    return (name, args)


class File:
    __slots__ = ['path', 'size', 'lines']

    def __init__(self, path, size, lines):
        self.path = path
        self.size = size
        self.lines = lines

    def report(self):
        return f'{strsize(self.size):>10}│{self.lines:>8}│  {relpath(self.path)}'


class Type:
    __slots__ = ['size', 'files', 'lines', 'entries']

    def __init__(self, size, files, lines, entries):
        self.size = size
        self.files = files
        self.lines = lines
        self.entries = entries

    def insert(self, file):
        self.entries.append(file)

    def summarize(self):
        for entry in self.entries:
            self.size += entry.size
            self.lines += entry.lines
        self.files = len(self.entries)


class Types(Type):
    __slots__ = []

    captions = ('Types', 'Size', 'Files', 'Lines')

    def __init__(self):
        super().__init__(0, 0, 0, {})

    def insert(self, type, file):
        if type not in self.entries:
            self.entries[type] = Type(0, 0, 0, [])
        self.entries[type].insert(file)

    def summarize(self):
        for entry in self.entries.values():
            entry.summarize()
            self.size += entry.size
            self.files += entry.files
            self.lines += entry.lines

    def report(self):
        types = Languages.report(self)
        paths = []
        for type in sorted(self.entries):
            data = self.entries[type]
            for file in data.entries:
                paths.append(file.report())
        paths = '\n'.join(paths)
        return types + '\n\n\n' + f"""
══════════╤════════╤══════════════════════════════════════════
      Size│   Lines│  Path
──────────┼────────┼──────────────────────────────────────────
{paths}
══════════╧════════╧══════════════════════════════════════════
"""


class Languages(Types):
    __slots__ = []

    captions = ('Languages', 'Size', 'Files', 'Lines')

    def insert(self, lang, type, path):
        if lang not in self.entries:
            self.entries[lang] = Types()
        size = try_or_zero(lambda: os.path.getsize(path))
        lines = try_or_zero(lambda: size and lc.count(path))
        file = File(path=path, size=size, lines=lines)
        self.entries[lang].insert(type, file)

    def report(self):
        m = max(19, max(map(len, self.entries)))
        row = "%{}s│%15s│%12s│%12s".format(m)
        entries = []
        for key in sorted(self.entries):
            data = self.entries[key]
            text = row % (key, strsize(data.size), data.files, data.lines)
            entries.append(text)
        caption = row % self.captions
        content = '\n'.join(entries)
        summary = ''
        if len(entries) > 1:
            summary = f"""
{m * '─'}┼───────────────┼────────────┼────────────
{row % ("Total", strsize(self.size), self.files, self.lines)}"""
        return f"""
{m * '═'}╤═══════════════╤════════════╤════════════
{caption}
{m * '─'}┼───────────────┼────────────┼────────────
{content}{summary}
{m * '═'}╧═══════════════╧════════════╧════════════
"""


class StatusBarTask:
    def __init__(self, function, message, success):
        self.function = function
        self.message = message
        self.success = success

    def attach(self, status_bar):
        self.status_bar = status_bar

    def status_message(self):
        return f'{self.message} {self.status_bar.status}'

    def finish_message(self):
        return self.success


class StatusBarThread:
    def __init__(self, task, window, key):
        self.state = 7
        self.step = 1
        self.last_view = None
        self.need_refresh = True
        self.window = window
        self.key = key
        self.status = ''
        self.task = task
        self.task.attach(self)
        self.thread = threading.Thread(target=task.function)
        self.thread.start()
        self.update_status_message()

    @contextmanager
    def pause(self):
        self.need_refresh = False
        yield
        self.need_refresh = True

    def update_status_message(self):
        self.update_status_bar()
        if self.need_refresh:
            self.show_status_message(self.task.status_message())
        if not self.thread.is_alive():
            cleanup = self.last_view.erase_status
            self.last_view.set_status(self.key, self.task.finish_message())
            sublime.set_timeout(lambda: cleanup(self.key), 2000)
        else:
            sublime.set_timeout(self.update_status_message, 100)

    def update_status_bar(self):
        if self.state == 0 or self.state == 7:
            self.step = -self.step
        self.state += self.step
        self.status = f"[{' ' * self.state}={' ' * (7 - self.state)}]"

    def show_status_message(self, message):
        active_view = self.window.active_view()
        active_view.set_status(self.key, message)
        if self.last_view != active_view:
            self.last_view and self.last_view.erase_status(self.key)
            self.last_view = active_view


def plugin_loaded():
    sublime.set_timeout_async(CodeLinesViewsManager.setup)


def plugin_unloaded():
    sublime.set_timeout_async(CodeLinesViewsManager.exit)
