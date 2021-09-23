import re
import os
import time
import functools

import sublime
import sublime_plugin

from .lib import Loger
from .lib import lc
from .lib import utils
from .lib.utils import cd, strsize, try_or_zero


class SideBarFileSizeCommand(sublime_plugin.WindowCommand):
    command = 'code_lines_file_size'

    def run(self, paths):
        self.window.run_command(self.command, {'path': paths[0]})

    def is_visible(self, paths):
        return len(paths) == 1 and os.path.exists(paths[0])


class SideBarCodeLinesCommand(SideBarFileSizeCommand):
    command = 'code_lines_in_directory'


class SideBarCodeLinesWithPatternCommand(SideBarFileSizeCommand):
    command = 'code_lines_in_directory_with_pattern'

    def is_visible(self, paths):
        return len(paths) == 1 and os.path.isdir(paths[0])


class CodeLinesShowTypesCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        if self.view.settings().has("cc_languages"):
            pt = self.view.sel()[0].a
            CodeLinesViewsManager.show_types_at(self.view, pt)


class CodeLinesOpenFileCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        if self.view.settings().has("cc_language"):
            pt = self.view.sel()[0].a
            CodeLinesViewsManager.open_file_at(self.view, pt)


class CodeLinesToggleLogCommand(sublime_plugin.WindowCommand):
    def run(self):
        Loger.debug = not Loger.debug


class PathInputHandler(sublime_plugin.TextInputHandler):
    def placeholder(self):
        return 'File Path'

    def initial_text(self):
        view = sublime.active_window().active_view()
        if view:
            path = view.file_name()
            if path and os.path.exists(path):
                return path
        return ''

    def validate(self, path):
        return os.path.exists(path)


class CodeLinesFileSizeCommand(sublime_plugin.WindowCommand):
    def run(self, path):
        Loger.threading(lambda: self.show_size(path), "Counting...", "Succeed.")

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
            def walk(dir):
                for name in os.listdir(dir):
                    path = os.path.join(dir, name)
                    if os.path.isfile(path):
                        self.files += 1
                        self.size += os.path.getsize(path)
                    else:
                        self.folders += 1
                        walk(path)
            with cd(path):
                walk('.')


class CodeLinesInDirectoryCommand(sublime_plugin.WindowCommand):
    def run(self, path):
        if os.path.isdir(path):
            self.count_directory(path)
        elif os.path.isfile(path):
            self.count_singel_file(path)

    def input(self, args):
        return PathInputHandler()

    def count_singel_file(self, path):
        message = f'The file {path} has {lc.count(path)} lines'
        sublime.message_dialog(message)

    def count_directory(self, path):
        Loger.threading(
            lambda: CodeLinesViewsManager.show_code_lines(
                self.window, path, self.walk),
            "Counting...", "Successful counting lines.")

    def walk(self):
        def count_dir(dir):
            for file in sorted(os.listdir(dir)):
                path = os.path.join(dir, file) if dir != '.' else file
                if os.path.isdir(path):
                    yield from count_dir(path)
                else:
                    yield path, file
        return count_dir('.')


class CodeLinesInDirectoryWithPatternCommand(CodeLinesInDirectoryCommand):
    initial_pattern = '.*'

    def count_directory(self, path):
        panel = self.window.show_input_panel(
            'File Pattern', self.initial_pattern,
            functools.partial(self.count_directory_with_pattern, path),
            None, None)
        panel.sel().clear()
        panel.sel().add(sublime.Region(0, len(self.initial_pattern)))

    def count_directory_with_pattern(self, path, pattern):
        self.pattern = pattern
        super().count_directory(path)

    def walk(self):
        return []


class CodeLinesViewsManager(sublime_plugin.EventListener):
    syntax_path = 'CodeLines.sublime-syntax'
    settings_name = 'CodeLines.sublime-settings'
    language_decider = lambda path: 'Plain Text'

    @classmethod
    def setup(cls):
        settings = sublime.load_settings(cls.settings_name)
        settings.clear_on_change("encoding")
        settings.add_on_change("encoding", lambda: cls.load(settings))
        cls.load(settings)
        lc.load_binary()

    @classmethod
    def exit(cls):
        lc.unload_binary()

    @classmethod
    def load(cls, settings):
        lc.set_encoding(settings.get("encoding", 'utf-8'))
        syntaxes = settings.get('syntaxes', [])
        ignored_syntaxes = settings.get('ignored_syntaxes', [])
        aliases_ = settings.get('aliases', {})
        aliases = {}
        for syntax in aliases_:
            for aliase in aliases_[syntax]:
                aliases[aliase] = syntax
        cls.language_decider = cls.create_language_decider(
            syntaxes, ignored_syntaxes, aliases)

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
    def show_code_lines(cls, window, rootdir, walk):
        window = sublime.active_window()
        cc_time = time.strftime("%Y/%m/%d/%H:%M")
        languages = count_lines_by_languages(rootdir, walk, cls.language_decider)
        cls.show_languages(window, rootdir, cc_time, languages)

    @classmethod
    def show_languages(cls, window, rootdir, cc_time, languages):
        if not languages.entries:
            window.status_message('CodeLines: No files')
            return
        cc_languages = {l: v.report() for l, v in languages.entries.items()}
        head = "ROOTDIR: %s\nTime: %s\n\n\n" % (rootdir, cc_time)
        body = languages.report()
        view = window.new_file()
        view.assign_syntax(cls.syntax_path)
        view.set_name("CodeLines")
        view.settings().set("font_face", "Lucida Console")
        view.settings().set("word_wrap", False)
        view.settings().set("translate_tabs_to_spaces", True)
        view.settings().set("rootdir", rootdir)
        view.settings().set("cc_time", cc_time)
        view.settings().set("cc_languages", cc_languages)
        view.run_command("append", {"characters": head + body})
        view.set_scratch(True)
        view.set_read_only(True)

    @classmethod
    def show_types(cls, view, rootdir, cc_time, lang, types_report):
        Loger.print("Show language:", lang)
        head = "ROOTDIR: %s\nTime: %s\n\n\n" % (rootdir, cc_time)
        body = types_report
        view = view.window().new_file()
        view.assign_syntax(cls.syntax_path)
        view.set_name("CodeLines - %s" % lang)
        view.settings().set("font_face", "Lucida Console")
        view.settings().set("word_wrap", False)
        view.settings().set("translate_tabs_to_spaces", True)
        view.settings().set("rootdir", rootdir)
        view.settings().set("cc_language", lang)
        view.run_command("append", {"characters": head + body})
        view.set_scratch(True)
        view.set_read_only(True)

    @classmethod
    def show_types_at(cls, view, pt):
        cc_languages = view.settings().get("cc_languages")
        lang = view.substr(view.extract_scope(pt))
        if lang in cc_languages:
            rootdir = view.settings().get("rootdir")
            cc_time = view.settings().get("cc_time")
            cls.show_types(view, rootdir, cc_time, lang, cc_languages[lang])
            return True
        return False

    @classmethod
    def open_file_at(cls, view, pt):
        rootdir = view.settings().get("rootdir")
        relpath = view.substr(view.extract_scope(pt))
        abspath = os.path.join(rootdir, relpath)
        if os.path.isfile(abspath):
            Loger.print("open source file:", abspath)
            view.window().open_file(abspath, sublime.ENCODED_POSITION)
            return True
        return False

    def on_text_command(self, view, name, args):
        # print(name, args)
        # Affected by `Chinese Words Cutter`
        if name == "drag_select" and args.get("by", "") == "words":
            event = args["event"]
            pt = view.window_to_text((event["x"], event["y"]))
            if view.settings().has("cc_language"):
                if CodeLinesViewsManager.open_file_at(view, pt):
                    return (name, args)
            elif view.settings().has("cc_languages"):
                if CodeLinesViewsManager.show_types_at(view, pt):
                    return (name, args)


class File:
    __slots__ = ['path', 'size', 'lines']

    def __init__(self, path, size, lines):
        self.path = path
        self.size = size
        self.lines = lines

    def report(self):
        return '%10s│%8d│  %s' % (strsize(self.size), self.lines, self.path)


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


def count_lines_by_languages(path, walk, decide_language):
    def count_file(path, file):
        lang = decide_language(file)
        if not lang:
            return
        ext = os.path.splitext(file)[1].lstrip('.')
        type = ext if ext else file
        languages.insert(lang, type, path)
    languages = Languages()
    with cd(path):
        for path, file in walk():
            count_file(path, file)
        languages.summarize()
    return languages


def plugin_loaded():
    sublime.set_timeout_async(CodeLinesViewsManager.setup)


def plugin_unloaded():
    sublime.set_timeout_async(CodeLinesViewsManager.exit)
