#!/usr/bin/env python

import argparse
from dataclasses import dataclass
import hashlib
import os
import pygubu
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from psxfoundry.gui import (
    DesktopAppMixin,
    CompletionDialog,
    ConversionTask,
    choose_image,
    clear_temporary_paths,
    import_disc_image,
    install_tk_error_handler,
    label_path_chooser,
    load_theme_image,
    read_preferences,
    reset_work_directory,
    show_conversion_error,
    write_preferences,
)
from popfe_psp_import import FolderImportError, scan_psp_folder
from popfe_runtime import runtime as popfe_runtime
from psxfoundry.cache import AnalysisCache
from psxfoundry.psp_workflow import (
    build_psp_plan,
    execution_decoded_sizes,
    expected_decoded_hashes,
    read_planned_configs,
)
from psxfoundry.report import (
    render_target_workflow_report,
    render_workflow_summary,
)
from psxfoundry.sbi import (
    SbiError,
    SbiSelection,
    load_sbi,
    resolve_sbi,
)
from psxfoundry.validation import EbootExpectation, validate_generated_eboot

have_pytube = False
try:
    import pytubefix as pytube
    have_pytube = True
except ImportError:
    pass

from PIL import Image
import importlib
from gamedb import games, libcrypt, themes
from layout import image_has_transparency
try:
    import popfe
except ImportError:
    popfe = importlib.import_module("pop-fe")

verbose = False
temp_files = []

DISC_FILETYPES = [
    ('PlayStation images', '*.cue *.ccd *.chd *.zip *.img *.bin *.iso'),
    ('All files', '*'),
]

PROJECT_PATH = popfe_runtime.resource_root
PROJECT_UI = popfe_runtime.resource_path("pop-fe-psp.ui", required=True)
PREFERENCES_PATH = popfe_runtime.application_preference_path(
    "psxfoundry-psp.config"
)
TARGET_VALUES = {
    'PSP': 'psp',
    'PS Vita / Adrenaline': 'adrenaline',
}
ADVANCED_LABELS = {
    'watermark': 'disc ID background',
    'disable_pic0': 'hidden game logo',
    'disable_pic1': 'hidden background image',
    'disable_snd0': 'muted XMB music',
    'ntsc_u_icon0': 'North American icon frame',
    'cdda': 'raw CD audio',
    'force_ntsc': 'forced 60 Hz output',
    'undither': 'reduced color dithering',
    'nopstitleimg': 'direct single-disc layout',
    'pic1aslogo': 'background startup logo',
    'pic0_scaling': 'logo size',
    'pic0_xoffset': 'horizontal logo position',
    'pic0_yoffset': 'vertical logo position',
}


@dataclass(frozen=True)
class PspConversionRequest:
    plan: object
    output_dir: str
    title: str
    disc_ids: tuple[str, ...]
    real_disc_ids: tuple[str, ...]
    cue_files: tuple[str, ...]
    real_cue_files: tuple[str, ...]
    image_files: tuple[str, ...]
    sbi_files: tuple[str | None, ...]
    sbi_origins: tuple[str | None, ...]
    work_dir: str
    snd0: str
    manual: str
    logo_path: str
    icon0: object
    pic0: object
    pic1: object
    disable_pic0: bool
    disable_pic1: bool
    disable_title_image: bool
    watermark: bool
    use_pic1_as_logo: bool
    undither: bool
    force_ntsc: bool
    use_cdda: bool
    manual_overrides: tuple[str, ...]


@dataclass(frozen=True)
class PreparedPspConversion:
    cue_files: tuple[str, ...]
    image_files: tuple[str, ...]
    audio_files: tuple[str, ...]
    subchannels: tuple[bytes | None, ...]
    planned_configs: tuple[bytes | None, ...]
    sound: object
    manual: object
    logo: object
    expectation: EbootExpectation


class PspApp(DesktopAppMixin):
    preview_audio_search = (
        pytube.contrib.search.Search if have_pytube else None
    )

    def __init__(self, master=None):
        self.myrect = None
        self.pkgdir = None
        self.watermark = 'on'
        self.nopstitleimg = 'off'
        self.pic1aslogo = 'off'
        self.cdda = 'off'
        self.pic0_disabled = 'off'
        self.pic1_disabled = 'off'
        self.snd0_disabled = 'off'
        self.subdir = str(
            popfe_runtime.application_work_dir("psp", "psxfoundry-psp-work")
        ) + os.sep
        self.pic0scaling = 0.9
        self.pic0xoffset = 0.1
        self.pic0yoffset = 0.1
        self.path_dir = None
        self.conversion_plan = None
        self.conversion_task = None
        self.advanced_visible = False
        self.advanced_overrides = set()
        self.analysis_cache = AnalysisCache(
            popfe_runtime.cache_dir / 'psxfoundry' / 'analysis'
        )
        
        self.master = master
        self.builder = builder = pygubu.Builder()
        builder.add_resource_path(PROJECT_PATH)
        builder.add_from_file(PROJECT_UI)
        self.mainwindow = builder.get_object("top_frame", master)

        builder.connect_callbacks(self)
        self._configure_layout()
        self.builder.get_variable('import_all_discs_variable').set('on')
        self.builder.get_object('target', self.master).configure(
            values=tuple(TARGET_VALUES),
            state='readonly',
        )
        self.builder.get_variable('target_variable').set('PSP')
        self.builder.get_object('frame4', self.master).grid_remove()
        for object_id in ('frame10', 'frame11', 'frame12'):
            self.builder.get_object(object_id, self.master).grid_remove()
        self.builder.get_object('frame4', self.master).columnconfigure(0, weight=1)
        self.builder.get_object('frame4', self.master).columnconfigure(1, weight=1)
        self._theme = ''
        theme_names = ('', *themes)
        self.builder.get_object('theme', self.master).configure(
            values=theme_names
        )
        self.init_data()
        try:
            self.read_prefs()
        except (OSError, ValueError):
            pass

    def __del__(self):
        clear_temporary_paths(temp_files, verbose=verbose)
        temp_files.clear()

    def _configure_layout(self):
        self.mainwindow.columnconfigure(0, weight=1, uniform='content')
        self.mainwindow.columnconfigure(1, weight=1, uniform='content')
        self._configure_source_layout()
        self._configure_preview_layout()
        self._configure_output_layout()
        self._configure_advanced_layout()

    def _configure_source_layout(self):
        source = self.builder.get_object('frame9', self.master)
        source.grid_configure(sticky='new')

        discs = self.builder.get_object('discs', self.master)
        discs.pack_configure(fill='x', expand=False)
        discs.columnconfigure(0, weight=1)
        for index in range(1, 6):
            chooser = self.builder.get_object(f'disc{index}', self.master)
            chooser.grid_configure(sticky='ew', pady=2)
            label_path_chooser(chooser, 'Choose disc...')
            self.builder.get_object(
                f'discid{index}', self.master
            ).grid_configure(padx=(6, 0), pady=2)

        self.builder.get_object('separator5', self.master).pack_forget()
        details = self.builder.get_object('frame1', self.master)
        details.pack_configure(fill='x', expand=False, pady=(8, 0))
        details.columnconfigure(0, weight=1)
        detail_rows = (
            ('title_frame', 'label9', 'title'),
            ('manual_frame', 'label2', 'manual'),
            ('frame3', 'label5', 'logo'),
            ('snd0_frame', 'label13', 'snd0'),
            ('theme_frame', 'label3', 'theme'),
        )
        for frame_id, label_id, input_id in detail_rows:
            row = self.builder.get_object(frame_id, self.master)
            row.grid_configure(sticky='ew', pady=3)
            row.columnconfigure(1, weight=1)
            self.builder.get_object(label_id, self.master).configure(
                anchor='e', width=13
            )
            self.builder.get_object(input_id, self.master).grid_configure(
                sticky='ew', padx=(8, 0)
            )

        self.builder.get_object('youtube_button', self.master).grid_configure(
            row=1, column=1, pady=(4, 0), sticky='e'
        )
        for object_id, text in (
            ('manual', 'Choose manual...'),
            ('logo', 'Choose logo...'),
            ('snd0', 'Choose audio...'),
            ('dir_input', 'Choose folder...'),
        ):
            label_path_chooser(
                self.builder.get_object(object_id, self.master), text
            )

    def _configure_preview_layout(self):
        preview_column = self.builder.get_object('frame7', self.master)
        preview_column.grid_configure(sticky='new')
        preview_column.columnconfigure(0, weight=1)
        preview = self.builder.get_object('preview', self.master)
        preview.grid_configure(sticky='n')
        for column in range(3):
            preview.columnconfigure(column, weight=1)
        self.builder.get_object('frame10', self.master).grid_configure(
            row=1, column=0, sticky='w'
        )
        self.builder.get_object('frame11', self.master).grid_configure(
            row=2, column=0, padx=(0, 8), sticky='w'
        )
        self.builder.get_object('frame12', self.master).grid_configure(
            row=2, column=1, sticky='w'
        )
        images = self.builder.get_object('images', self.master)
        images.grid_configure(sticky='ew', pady=(10, 0))
        for column in range(3):
            images.columnconfigure(column, weight=1, uniform='artwork')

    def _configure_output_layout(self):
        output = self.builder.get_object('output_frame', self.master)
        output.columnconfigure(1, weight=1)
        self.builder.get_object('label15', self.master).configure(
            anchor='e', width=8
        )
        self.builder.get_object('create_button', self.master).configure(width=22)

    def _configure_advanced_layout(self):
        advanced = self.builder.get_object('frame4', self.master)
        advanced.configure(padding=10)
        for column in range(2):
            advanced.columnconfigure(column, weight=1, uniform='advanced')
        for object_id in ('artwork_settings', 'compatibility_settings'):
            panel = self.builder.get_object(object_id, self.master)
            panel.configure(padding=8)
            panel.columnconfigure(1, weight=1)

        option_groups = (
            (
                ('watermark', 'watermark_help'),
                ('disable_pic0', 'disable_pic0_help'),
                ('disable_pic1', 'disable_pic1_help'),
                ('disable_snd0', 'disable_snd0_help'),
                ('ntsc_u_icon0', 'ntsc_u_icon0_help'),
            ),
            (
                ('use_cdda', 'use_cdda_help'),
                ('force_ntsc', 'force_ntsc_help'),
                ('use_psx_undither', 'use_psx_undither_help'),
                ('nopstitleimg', 'nopstitleimg_help'),
                ('pic1aslogo', 'pic1aslogo_help'),
            ),
        )
        for group in option_groups:
            for row, (option_id, help_id) in enumerate(group):
                self.builder.get_object(
                    option_id, self.master
                ).grid_configure(row=row, column=0, pady=2, sticky='w')
                help_label = self.builder.get_object(help_id, self.master)
                help_label.configure(wraplength=320)
                help_label.grid_configure(
                    row=row, column=1, padx=(8, 4), pady=2, sticky='w'
                )

    def _manual_override_labels(self):
        return tuple(
            label
            for key, label in ADVANCED_LABELS.items()
            if key in self.advanced_overrides
        )

    def _update_advanced_status(self):
        labels = self._manual_override_labels()
        status = (
            'Manual changes: ' + ', '.join(labels)
            if labels
            else 'Mode: Automatic'
        )
        self.builder.get_variable('advanced_status_variable').set(status)
        self.builder.get_object(
            'restore_automatic_button', self.master
        ).configure(state='normal' if labels else 'disabled')

    def _update_plan_summary(self):
        if self.conversion_plan is None:
            self.builder.get_variable('plan_summary_variable').set('')
            return
        summary = render_workflow_summary(self.conversion_plan)
        labels = self._manual_override_labels()
        if labels:
            summary += '\nManual changes: ' + ', '.join(labels)
        sbi_summary = self._sbi_summary()
        if sbi_summary:
            summary += '\n' + sbi_summary
        self.builder.get_variable('plan_summary_variable').set(summary)

    def _mark_advanced_override(self, name):
        self.advanced_overrides.add(name)
        self._update_advanced_status()
        self._update_plan_summary()

    def _automatic_logo_layout(self):
        if self.disc_ids and self.disc_ids[0] in games:
            game = games[self.disc_ids[0]]
            scaling = game.get('pic0-scaling', 0.9)
            xoffset, yoffset = game.get('pic0-offset', (0.1, 0.1))
            return scaling, xoffset, yoffset
        return 0.9, 0.1, 0.1

    def _apply_automatic_settings(self, refresh_assets=False):
        plan = self.conversion_plan
        settings = {
            'watermark_variable': 'on',
            'pic0_disabled_variable': 'off',
            'pic1_disabled_variable': 'off',
            'snd0_disabled_variable': 'off',
            'ntsc_u_icon0_variable': 'off',
            'cdda_variable': 'on' if plan and plan.use_cdda else 'off',
            'force_ntsc_variable': 'on' if plan and plan.force_ntsc else 'off',
            'psx_undither_variable': 'on' if plan and plan.undither else 'off',
            'nopstitleimg_variable': 'off',
            'pic1aslogo_variable': 'off',
        }
        for variable, value in settings.items():
            self.builder.get_variable(variable).set(value)

        self.watermark = settings['watermark_variable']
        self.pic0_disabled = settings['pic0_disabled_variable']
        self.pic1_disabled = settings['pic1_disabled_variable']
        self.snd0_disabled = settings['snd0_disabled_variable']
        self.cdda = settings['cdda_variable']
        self.nopstitleimg = settings['nopstitleimg_variable']
        self.pic1aslogo = settings['pic1aslogo_variable']

        self.pic0scaling, self.pic0xoffset, self.pic0yoffset = (
            self._automatic_logo_layout()
        )
        self.builder.get_variable('pic0scaling_variable').set(self.pic0scaling)
        self.builder.get_variable('pic0xoffset_variable').set(self.pic0xoffset)
        self.builder.get_variable('pic0yoffset_variable').set(self.pic0yoffset)

        self.advanced_overrides.clear()
        self._update_advanced_status()
        self._update_plan_summary()
        if refresh_assets and self.disc_ids:
            self.update_assets(update_pic0=False, update_pic1=False)

    def _apply_plan_settings(self):
        plan_settings = (
            ('cdda', 'cdda_variable', self.conversion_plan.use_cdda),
            ('force_ntsc', 'force_ntsc_variable', self.conversion_plan.force_ntsc),
            ('undither', 'psx_undither_variable', self.conversion_plan.undither),
        )
        for name, variable, enabled in plan_settings:
            if name not in self.advanced_overrides:
                self.builder.get_variable(variable).set(
                    'on' if enabled else 'off'
                )
        self.cdda = self.builder.get_variable('cdda_variable').get()
        self._update_advanced_status()
        self._update_plan_summary()

    def init_data(self):
        reset_work_directory(self.subdir, temp_files)

        self._reset_imported_discs()
        self._reset_artwork()
        self.sbi_selections = []
        self.sbi_errors = []
        self.sbi_checked = []
        self.icon0_path = None
        self.snd0_path = None
        for disc_number in range(1, 6):
            disc_input = self.builder.get_object(
                f'disc{disc_number}', self.master
            )
            disc_input.configure(
                filetypes=[
                    ('Image files', ['.cue', '.ccd', '.img', '.iso', '.zip', '.chd']),
                    ('All Files', ['*.*', '*']),
                ],
                state='disabled',
            )
            self._clear_variables(
                f'disc{disc_number}_variable',
                f'discid{disc_number}_variable',
            )
            for object_id in (
                f'disc{disc_number}',
                f'discid{disc_number}',
                f'sbi{disc_number}_button',
            ):
                self.builder.get_object(object_id, self.master).grid_remove()
        self._set_controls_state('normal', 'add_disc_button')
        self._set_controls_state(
            'disabled',
            'create_button',
            'youtube_button',
            'pic0scaling',
            'pic0xoffset',
            'pic0yoffset',
            'manual',
        )
        self._clear_variables(
            'title_variable',
            'snd0_variable',
            'logo_variable',
            'manual_variable',
            'pic0scaling_variable',
            'pic0xoffset_variable',
            'pic0yoffset_variable',
            'import_summary_variable',
            'plan_summary_variable',
        )
        self.builder.get_object('snd0', self.master).configure(
            filetypes=[
                ('Audio files', ['.wav']),
                ('All Files', ['*.*', '*']),
            ]
        )
        self.builder.get_object('logo', self.master).configure(
            filetypes=[
                ('Image files', ['.png', '.PNG']),
                ('All Files', ['*.*', '*']),
            ]
        )
        self.builder.get_object('manual', self.master).configure(
            filetypes=[('All Files', ['*.*', '*'])]
        )
        self.conversion_plan = None
        self._apply_automatic_settings()

    def update_prefs(self):
        preferences = [
            (
                'target',
                self.builder.get_variable('target_variable').get(),
            ),
            ('dir', self.builder.get_variable('pkgdir_variable').get()),
        ]
        if self.path_dir:
            preferences.append(('path', self.path_dir))
        write_preferences(PREFERENCES_PATH, preferences)

    def read_prefs(self):
        preferences = read_preferences(PREFERENCES_PATH)
        target = preferences.get('target')
        if target in TARGET_VALUES:
            self.builder.get_variable('target_variable').set(target)

        output_directory = preferences.get('dir')
        if output_directory is not None:
            self.builder.get_variable('pkgdir_variable').set(output_directory)
            self.pkgdir = output_directory

        self.path_dir = preferences.get('path', self.path_dir)
        if self.path_dir:
            self._set_disc_initial_directory(self.path_dir)

    def _load_logo_artwork(self, disc_id, game):
        self.pic0 = None
        if self.pic0_path:
            self.pic0 = Image.open(self.pic0_path)
            self.pic0_orig = self.pic0.copy()
        if not self.pic0 and self._theme:
            self.pic0_orig = load_theme_image(
                popfe.get_image_from_theme,
                self._theme,
                disc_id,
                self.subdir,
                'PIC0',
            )
            self.pic0 = self.pic0_orig
        if not self.pic0:
            if game is None and disc_id in games:
                game = popfe.get_game_from_gamelist(disc_id)
            self.pic0_orig = popfe.get_pic0_from_game(
                disc_id,
                game,
                self.cue_file_orig,
                no_scaling=True,
            )
            self.pic0 = popfe.rescale_pic0(
                self.pic0_orig,
                self.pic0scaling,
                (self.pic0xoffset, self.pic0yoffset),
            )
        if self.pic0:
            self._render_artwork_preview('pic0', (128, 80), temp_files)

    def _load_icon_artwork(self, disc_id, game):
        self.icon0 = None
        if self.icon0_path:
            self.icon0 = Image.open(self.icon0_path)
        elif self._theme:
            self.icon0 = load_theme_image(
                popfe.get_image_from_theme,
                self._theme,
                disc_id,
                self.subdir,
                'ICON0',
            )
            if self.icon0:
                self.icon0 = self.icon0.crop(self.icon0.getbbox())

        if not self.icon0:
            if disc_id in games:
                self.icon0 = popfe.get_icon0_from_game(
                    disc_id,
                    game,
                    self.cue_file_orig,
                    self.subdir + 'ICON0.PNG',
                    psp_ntsc_u_frame=(
                        self.builder.get_variable(
                            'ntsc_u_icon0_variable'
                        ).get() == 'on'
                    ),
                    psn_frame_size=((80, 80), (62, 62)),
                )
            else:
                self.icon0 = Image.new(
                    'RGBA', (80, 80), (255, 255, 255, 0)
                )

        if self.icon0:
            self._render_artwork_preview('icon0', (80, 80), temp_files)

    def _load_preview_audio(self, disc_id):
        if self.snd0_disabled != 'off':
            return

        audio_path = self.snd0_path
        if not audio_path and self._theme:
            audio_path = popfe.get_snd0_from_theme(
                self._theme, disc_id, self.subdir
            )
            if audio_path:
                temp_files.append(audio_path)
        if not audio_path:
            audio_path = games.get(disc_id, {}).get('snd0')
        if audio_path:
            self.builder.get_variable('snd0_variable').set(audio_path)

    def update_assets(
        self,
        update_icon0=True,
        update_pic0=True,
        update_pic1=True,
    ):
        if not self.disc_ids or not self.cue_file_orig:
            return

        disc_id = self.disc_ids[0]
        needs_game_data = (
            (update_icon0 and not self.icon0_path)
            or (update_pic0 and not self.pic0_path)
            or (update_pic1 and not self.pic1_path)
        )
        game = (
            popfe.get_game_from_gamelist(disc_id)
            if needs_game_data and disc_id in games
            else None
        )

        if update_icon0:
            if verbose:
                print('Fetching ICON0')
            self._load_icon_artwork(disc_id, game)

        if self.snd0_disabled == 'off':
            if verbose:
                print('Fetching SND0')
            self._load_preview_audio(disc_id)

        if update_pic0:
            if verbose:
                print('Fetching PIC0')
            self._load_logo_artwork(disc_id, game)

        if update_pic1:
            if verbose:
                print('Fetching PIC1')
            self._load_background_artwork(
                popfe, temp_files, disc_id, game
            )

        self.update_preview()

    def _expected_sbi_magic(self, disc_id):
        entry = libcrypt.get(disc_id)
        return entry.get('magic_word') if entry else None

    def _planned_sbi_magic(self, index):
        if (
            self.conversion_plan is not None
            and index < len(self.conversion_plan.discs)
        ):
            planned = self.conversion_plan.discs[index].libcrypt_magic_word
            if planned is not None:
                return planned
        return self._expected_sbi_magic(self.real_disc_ids[index])

    def _sbi_summary(self):
        parts = []
        labels = {
            'local': 'local SBI',
            'manual': 'manual SBI',
            'downloaded': 'downloaded SBI',
            'cached': 'cached SBI',
        }
        for index, _ in enumerate(self.real_disc_ids or []):
            selection = self.sbi_selections[index]
            if selection is not None:
                parts.append(
                    f'Disc {index + 1}: {labels[selection.origin]}'
                )
            elif self._planned_sbi_magic(index):
                parts.append(f'Disc {index + 1}: SBI missing')
        return 'Protection data: ' + '; '.join(parts) if parts else ''

    def _update_sbi_button(self, index):
        button = self.builder.get_object(
            'sbi%d_button' % (index + 1), self.master
        )
        selection = self.sbi_selections[index]
        expected = self._planned_sbi_magic(index)
        if expected == 0:
            text = 'SBI: not needed'
            state = 'disabled'
        elif selection is not None:
            labels = {
                'local': 'SBI: local',
                'manual': 'SBI: manual',
                'downloaded': 'SBI: online',
                'cached': 'SBI: cached',
            }
            text = labels[selection.origin]
            state = 'normal'
        elif expected:
            text = 'SBI: missing'
            state = 'normal'
        else:
            text = 'Select SBI...'
            state = 'normal'
        button.configure(text=text, state=state)

    def _resolve_disc_sbi(self, source_path, disc_id):
        expected = self._expected_sbi_magic(disc_id)
        result = resolve_sbi(
            source_path,
            disc_id,
            expected_magic_word=expected,
            cache_dir=popfe_runtime.cache_dir / 'psxfoundry' / 'sbi',
        )
        return result.selection, result.error

    def _select_sbi(self, index):
        if index >= len(self.cue_files) or self.conversion_plan is None:
            return
        if self._planned_sbi_magic(index) == 0:
            return
        source_path = self.real_cue_files[index]
        path = filedialog.askopenfilename(
            title='Select SBI for disc %d' % (index + 1),
            initialdir=str(Path(source_path).parent),
            filetypes=[('SBI files', '*.sbi'), ('All files', '*')],
        )
        if not path:
            return
        disc = self.conversion_plan.discs[index]
        try:
            data = load_sbi(
                path,
                expected_magic_word=disc.libcrypt_magic_word,
                sector_count=disc.description.sector_count,
            )
        except SbiError as error:
            messagebox.showerror('Invalid SBI file', str(error), parent=self.master)
            return
        self.sbi_selections[index] = SbiSelection(
            Path(path).resolve(), 'manual', data
        )
        self.sbi_errors[index] = None
        self.sbi_checked[index] = True
        self._update_sbi_button(index)
        self._update_plan_summary()

    def on_sbi1_clicked(self):
        self._select_sbi(0)

    def on_sbi2_clicked(self):
        self._select_sbi(1)

    def on_sbi3_clicked(self):
        self._select_sbi(2)

    def on_sbi4_clicked(self):
        self._select_sbi(3)

    def on_sbi5_clicked(self):
        self._select_sbi(4)

    def _sync_disc_rows(self):
        loaded_count = len(self.cue_files)
        for disc_number in range(1, 6):
            chooser = self.builder.get_object(
                f'disc{disc_number}', self.master
            )
            disc_id_input = self.builder.get_object(
                f'discid{disc_number}', self.master
            )
            sbi_button = self.builder.get_object(
                f'sbi{disc_number}_button', self.master
            )
            if disc_number <= loaded_count:
                chooser.grid()
                disc_id_input.grid()
                sbi_button.grid()
                chooser.config(state='disabled')
                disc_id_input.config(state='normal')
                self._update_sbi_button(disc_number - 1)
            else:
                chooser.grid_remove()
                disc_id_input.grid_remove()
                sbi_button.grid_remove()
        self.builder.get_object('add_disc_button', self.master).config(
            state='disabled' if loaded_count >= 5 else 'normal'
        )

    def _target(self):
        selected = self.builder.get_variable('target_variable').get()
        return TARGET_VALUES.get(selected, 'psp')

    def _refresh_conversion_plan(self, allow_missing_fixes=False):
        if not self.cue_files:
            self.conversion_plan = None
            self.builder.get_variable('plan_summary_variable').set('')
            return None

        self.conversion_plan = None
        plan = build_psp_plan(
            self.cue_files,
            self._target(),
            fallback_disc_ids=self.real_disc_ids,
            analysis_cache=self.analysis_cache,
            allow_missing_fixes=allow_missing_fixes,
        )
        self.conversion_plan = plan
        for index, disc in enumerate(plan.discs):
            if disc.libcrypt_magic_word == 0:
                self.sbi_selections[index] = None
                self.sbi_errors[index] = None
                self.sbi_checked[index] = True
            elif disc.libcrypt_magic_word and not self.sbi_checked[index]:
                source_path = self.builder.get_variable(
                    'disc%d_variable' % (index + 1)
                ).get()
                selection, error = self._resolve_disc_sbi(
                    source_path,
                    self.real_disc_ids[index],
                )
                self.sbi_selections[index] = selection
                self.sbi_errors[index] = error
                self.sbi_checked[index] = True
            self._update_sbi_button(index)
        for disc_number, disc_id in enumerate(plan.output_disc_ids, start=1):
            self.builder.get_variable(
                f'discid{disc_number}_variable'
            ).set(disc_id)
        self._apply_plan_settings()
        return plan

    def on_target_selected(self, event=None):
        self.update_prefs()
        if not self.cue_files:
            return
        self.master.config(cursor='watch')
        self.master.update()
        try:
            self._refresh_conversion_plan_with_prompt()
        except Exception as error:
            messagebox.showerror(
                'Could not plan conversion', str(error), parent=self.master
            )
        finally:
            self.master.config(cursor='')

    def on_toggle_advanced(self):
        frame = self.builder.get_object('frame4', self.master)
        button = self.builder.get_object('advanced_button', self.master)
        layout_frames = tuple(
            self.builder.get_object(object_id, self.master)
            for object_id in ('frame10', 'frame11', 'frame12')
        )
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            frame.grid()
            for layout_frame in layout_frames:
                layout_frame.grid()
            button.configure(text='Hide advanced settings')
        else:
            frame.grid_remove()
            for layout_frame in layout_frames:
                layout_frame.grid_remove()
            button.configure(text='Advanced settings')

    def on_restore_automatic(self):
        self._apply_automatic_settings(refresh_assets=True)

    def _apply_game_defaults(self, disc_id, game):
        if not self.manual and 'manual' in game:
            if verbose:
                print('Found a manual for', disc_id)
            self.manual = game['manual']
        if 'psp-use-cdda' in game:
            self.cdda = 'on'
            self.builder.get_variable('cdda_variable').set(self.cdda)

    def _configure_first_disc(self, disc_id, game, fallback_title):
        title = popfe.get_title_from_game(disc_id)
        if title == 'Unknown' and fallback_title:
            title = fallback_title
        self.builder.get_variable('title_variable').set(title)

        self.pic0scaling = game.get('pic0-scaling', 0.9)
        self.pic0xoffset, self.pic0yoffset = game.get(
            'pic0-offset', (0.1, 0.1)
        )
        values = {
            'pic0scaling_variable': self.pic0scaling,
            'pic0xoffset_variable': self.pic0xoffset,
            'pic0yoffset_variable': self.pic0yoffset,
            'manual_variable': self.manual or '',
        }
        for variable_name, value in values.items():
            self.builder.get_variable(variable_name).set(value)
        self._set_controls_state(
            'normal',
            'pic0scaling',
            'pic0xoffset',
            'pic0yoffset',
            'manual',
            'youtube_button',
            'create_button',
        )
        self.update_assets()

    def load_disc(
        self,
        source_path,
        disc_number,
        fallback_title=None,
        refresh_plan=True,
    ):
        if disc_number != len(self.cue_files) + 1 or disc_number > 5:
            raise ValueError('Discs must be loaded in order, up to five.')

        source_path = os.path.abspath(source_path)
        self.path_dir = os.path.dirname(source_path)
        self.builder.get_variable(
            f'disc{disc_number}_variable'
        ).set(source_path)
        if verbose:
            print('Processing', source_path)

        disc = import_disc_image(
            popfe,
            source_path,
            disc_number,
            temp_files,
            self.subdir,
            is_psp=True,
        )
        if verbose:
            print('ID', disc.disc_id)
        self.builder.get_variable(
            f'discid{disc_number}_variable'
        ).set(disc.disc_id)
        self._record_imported_disc(disc)
        self.sbi_selections.append(None)
        self.sbi_errors.append(None)
        self.sbi_checked.append(False)

        game = games.get(disc.disc_id, {})
        self._apply_game_defaults(disc.disc_id, game)
        if disc_number == 1:
            self._configure_first_disc(
                disc.disc_id, game, fallback_title
            )

        self._sync_disc_rows()
        if refresh_plan:
            self._refresh_conversion_plan()
        self.update_prefs()
        if verbose:
            print('Finished processing disc')

    def _load_disc_with_dialog(
        self, source_path, disc_number, fallback_title=None
    ):
        self.master.config(cursor='watch')
        self.master.update()
        try:
            self.load_disc(
                source_path,
                disc_number,
                fallback_title=fallback_title,
                refresh_plan=False,
            )
            if self._refresh_conversion_plan_with_prompt() is None:
                return False
        except Exception as error:
            messagebox.showerror('Could not load disc', str(error), parent=self.master)
            return False
        finally:
            self.master.config(cursor='')
        return True

    def on_add_disc(self):
        disc_number = len(self.cue_files) + 1
        if disc_number > 5:
            return
        source_path = filedialog.askopenfilename(
            title='Select PlayStation disc image',
            initialdir=self.path_dir or str(popfe_runtime.home),
            filetypes=DISC_FILETYPES,
        )
        if source_path:
            self._load_disc_with_dialog(source_path, disc_number)

    def _apply_folder_assets(self, assets):
        self.icon0_path = str(assets['icon0']) if 'icon0' in assets else None
        self.pic0_path = str(assets['pic0']) if 'pic0' in assets else None
        self.pic1_path = str(assets['pic1']) if 'pic1' in assets else None
        self.snd0_path = str(assets['snd0']) if 'snd0' in assets else None
        self.manual = str(assets['manual']) if 'manual' in assets else None
        self.builder.get_variable('snd0_variable').set(self.snd0_path or '')
        self.builder.get_variable('manual_variable').set(self.manual or '')
        self.builder.get_variable('logo_variable').set(
            str(assets['logo']) if 'logo' in assets else ''
        )

    def _set_folder_import_summary(self, result):
        labels = {
            'icon0': 'ICON0',
            'pic0': 'PIC0',
            'pic1': 'PIC1',
            'snd0': 'SND0',
            'manual': 'manual',
            'logo': 'logo',
        }
        local = [labels[field] for field in labels if field in result.assets]
        automatic = []
        resolved = {
            'icon0': self.icon0,
            'pic0': self.pic0,
            'pic1': self.pic1,
            'snd0': self.builder.get_variable('snd0_variable').get(),
            'manual': self.builder.get_variable('manual_variable').get(),
        }
        for field, value in resolved.items():
            if field not in result.assets and value:
                automatic.append(labels[field])

        parts = [
            'Loaded %d disc%s' % (
                len(result.discs), '' if len(result.discs) == 1 else 's'
            )
        ]
        if local:
            parts.append('Local: ' + ', '.join(local))
        if automatic:
            parts.append('Automatic: ' + ', '.join(automatic))
        sbi_local = sum(
            selection is not None and selection.origin in {'local', 'manual'}
            for selection in self.sbi_selections
        )
        sbi_online = sum(
            selection is not None and selection.origin in {'downloaded', 'cached'}
            for selection in self.sbi_selections
        )
        if sbi_local:
            parts.append('Local SBI: %d' % sbi_local)
        if sbi_online:
            parts.append('Automatic SBI: %d' % sbi_online)
        parts.extend(result.warnings)
        self.builder.get_variable('import_summary_variable').set('  |  '.join(parts))

    def import_folder(
        self,
        directory,
        import_all_discs=True,
        prompt_for_missing_fix=False,
    ):
        result = scan_psp_folder(
            directory,
            import_all_discs=import_all_discs,
        )
        self.init_data()
        self.path_dir = str(result.directory)
        self._apply_folder_assets(result.assets)
        for disc_number, source_path in enumerate(result.discs, start=1):
            self.load_disc(
                str(source_path),
                disc_number,
                fallback_title=(
                    result.fallback_title if disc_number == 1 else None
                ),
                refresh_plan=False,
            )
        if prompt_for_missing_fix:
            self._refresh_conversion_plan_with_prompt()
        else:
            self._refresh_conversion_plan()
        self._set_folder_import_summary(result)
        self.update_prefs()
        return result

    def on_import_folder(self):
        directory = filedialog.askdirectory(
            title='Import PlayStation game folder',
            initialdir=self.path_dir or str(popfe_runtime.home),
        )
        if not directory:
            return

        self.master.config(cursor='watch')
        self.master.update()
        try:
            self.import_folder(
                directory,
                import_all_discs=(
                    self.builder.get_variable('import_all_discs_variable').get()
                    == 'on'
                ),
                prompt_for_missing_fix=True,
            )
        except FolderImportError as error:
            messagebox.showerror('Could not import folder', str(error), parent=self.master)
        except Exception as error:
            self.init_data()
            messagebox.showerror('Could not import folder', str(error), parent=self.master)
        finally:
            self.master.config(cursor='')

    def on_path_changed(self, event):
        source_path = event.widget.cget('path')
        if not source_path:
            return
        disc_number = int(event.widget.cget('title')[1])
        self._load_disc_with_dialog(source_path, disc_number)


    def update_preview(self):
        if not self.disc_ids:
            return

        if self.pic0_disabled == 'on':
            logo = None
        else:
            logo = popfe.rescale_pic0(
                self.pic0_orig,
                self.pic0scaling,
                (self.pic0xoffset, self.pic0yoffset),
            )
        if self.pic1_disabled == 'on':
            background = None
        else:
            background = self.pic1

        if logo and logo.mode == 'P':
            logo = logo.convert(mode='RGBA')
        if background:
            preview = background.resize(
                (382, 216), Image.Resampling.HAMMING
            )
        else:
            preview = Image.new('RGBA', (382, 216), (0, 0, 0, 0))
        preview = preview.convert('RGBA')

        if logo:
            logo = logo.resize(
                (
                    int(preview.size[0] * 0.55),
                    int(preview.size[1] * 0.58),
                ),
                Image.Resampling.HAMMING,
            )
            preview.paste(
                logo,
                (148, 79),
                logo if image_has_transparency(logo) else None,
            )
        if self.icon0:
            icon_size = int(preview.size[1] * 0.25)
            icon = self.icon0.resize(
                (icon_size, icon_size), Image.Resampling.HAMMING
            )
            preview.paste(
                icon,
                (36, 81),
                icon if image_has_transparency(icon) else None,
            )

        preview_path = self.subdir + 'PREVIEW.PNG'
        temp_files.append(preview_path)
        preview.save(preview_path)
        self.preview_tk = tk.PhotoImage(file=preview_path)
        canvas = self.builder.get_object('preview_canvas', self.master)
        canvas.delete('all')
        canvas.create_image(0, 0, image=self.preview_tk, anchor='nw')
        

    def on_nopstitleimg(self):
        self.nopstitleimg = self.builder.get_variable('nopstitleimg_variable').get()
        self._mark_advanced_override('nopstitleimg')
        
    def on_pic1aslogo(self):
        self.pic1aslogo = self.builder.get_variable('pic1aslogo_variable').get()
        self._mark_advanced_override('pic1aslogo')
        
    def on_watermark(self):
        self.watermark = self.builder.get_variable('watermark_variable').get()
        self._mark_advanced_override('watermark')
        
    def on_icon0_clicked(self, event):
        path, image = choose_image(self.master, 'Select image for ICON0')
        if image is None:
            return
        self.icon0 = image
        self.icon0_path = path
        self.update_assets(update_pic0=False, update_pic1=False)
        self.update_preview()


    def on_pic0_disabled(self):
        self.pic0_disabled = self.builder.get_variable('pic0_disabled_variable').get()
        self._mark_advanced_override('disable_pic0')
        self.update_preview()

    def on_pic1_disabled(self):
        self.pic1_disabled = self.builder.get_variable('pic1_disabled_variable').get()
        self._mark_advanced_override('disable_pic1')
        self.update_preview()

    def on_snd0_disabled(self):
        self.snd0_disabled = self.builder.get_variable('snd0_disabled_variable').get()
        self._mark_advanced_override('disable_snd0')

    def on_pic0_clicked(self, event):
        path, image = choose_image(self.master, 'Select image for PIC0')
        if image is None:
            return
        self.pic0 = image
        self.pic0_orig = image.copy()
        self.pic0_path = path
        self._render_artwork_preview('pic0', (128, 80), temp_files)
        self.update_preview()
        
    def on_pic1_clicked(self, event):
        path, image = choose_image(self.master, 'Select image for PIC1')
        if image is None:
            return
        self.pic1 = image
        self.pic1_path = path
        self._render_artwork_preview('pic1', (128, 80), temp_files)
        self.update_preview()

    def on_pic0_scaling(self, event):
        try:
            value = float(
                self.builder.get_variable('pic0scaling_variable').get()
            )
        except ValueError:
            return

        if value > 0.1 and value != self.pic0scaling and self.disc_ids:
            self.pic0scaling = value
            self._mark_advanced_override('pic0_scaling')
            self.update_preview()

    def on_pic0_xoffset(self, event):
        try:
            value = float(
                self.builder.get_variable('pic0xoffset_variable').get()
            )
        except ValueError:
            return

        if value != self.pic0xoffset and self.disc_ids:
            self.pic0xoffset = value
            self._mark_advanced_override('pic0_xoffset')
            self.update_preview()
            
    def on_pic0_yoffset(self, event):
        try:
            value = float(
                self.builder.get_variable('pic0yoffset_variable').get()
            )
        except ValueError:
            return

        if value != self.pic0yoffset and self.disc_ids:
            self.pic0yoffset = value
            self._mark_advanced_override('pic0_yoffset')
            self.update_preview()
            
    def _build_conversion_request(self, plan):
        output_dir = self.builder.get_variable('pkgdir_variable').get()
        if not output_dir:
            output_dir = str(popfe_runtime.home) if popfe_runtime.is_macos else '.'

        return PspConversionRequest(
            plan=plan,
            output_dir=output_dir,
            title=self.builder.get_variable('title_variable').get(),
            disc_ids=tuple(
                self.builder.get_variable(
                    f'discid{index + 1}_variable'
                ).get()
                for index in range(len(self.cue_files))
            ),
            real_disc_ids=tuple(self.real_disc_ids),
            cue_files=tuple(self.cue_files),
            real_cue_files=tuple(self.real_cue_files),
            image_files=tuple(self.image_files),
            sbi_files=tuple(
                str(selection.path) if selection is not None else None
                for selection in self.sbi_selections
            ),
            sbi_origins=tuple(
                selection.origin if selection is not None else None
                for selection in self.sbi_selections
            ),
            work_dir=self.subdir,
            snd0=self.builder.get_variable('snd0_variable').get(),
            manual=self.builder.get_variable('manual_variable').get(),
            logo_path=self.builder.get_variable('logo_variable').get(),
            icon0=self.icon0.copy() if self.icon0 else None,
            pic0=self.pic0.copy() if self.pic0 else None,
            pic1=self.pic1.copy() if self.pic1 else None,
            disable_pic0=self.pic0_disabled == 'on',
            disable_pic1=self.pic1_disabled == 'on',
            disable_title_image=self.nopstitleimg == 'on',
            watermark=self.watermark == 'on',
            use_pic1_as_logo=self.pic1aslogo == 'on',
            undither=(
                self.builder.get_variable('psx_undither_variable').get() == 'on'
            ),
            force_ntsc=(
                self.builder.get_variable('force_ntsc_variable').get() == 'on'
            ),
            use_cdda=self.builder.get_variable('cdda_variable').get() == 'on',
            manual_overrides=self._manual_override_labels(),
        )

    def _prepare_psp_assets(self, request, set_phase):
        set_phase('Preparing assets...')
        sound = request.snd0
        if sound.startswith('https://www.youtube.com/'):
            sound = popfe.get_snd0_from_link(sound, subdir=request.work_dir)
            if sound:
                temp_files.append(sound)

        manual = request.manual
        if manual and manual != 'None':
            manual = popfe.create_manual(
                manual,
                request.real_disc_ids[0],
                subdir=request.work_dir,
            )
        else:
            manual = None

        logo = Image.open(request.logo_path) if request.logo_path else None
        if request.use_pic1_as_logo:
            logo = request.pic1
        return sound, manual, logo

    def _build_eboot_expectation(
        self,
        request,
        working_cues,
        working_images,
        subchannels,
    ):
        expected_configs = read_planned_configs(
            request.plan,
            force_ntsc=request.force_ntsc,
            cdda=request.use_cdda,
        )
        return EbootExpectation(
            disc_ids=request.disc_ids,
            decoded_sizes=execution_decoded_sizes(
                request.plan,
                use_cdda=request.use_cdda,
            ),
            decoded_sha256=expected_decoded_hashes(
                request.plan,
                working_images,
                use_cdda=request.use_cdda,
            ),
            tocs=tuple(
                bytes(popfe.get_toc_from_cue(cue)).ljust(1020, b'\x00')
                for cue in working_cues
            ),
            configs=expected_configs,
            subchannel_records=tuple(
                len(data) // 12 if data is not None else 0
                for data in subchannels
            ),
            subchannel_sha256=tuple(
                hashlib.sha256(data).hexdigest()
                if data is not None
                else None
                for data in subchannels
            ),
        )

    def _prepare_psp_conversion(self, request, set_phase):
        sound, manual, logo = self._prepare_psp_assets(request, set_phase)
        set_phase('Applying compatibility fixes...')
        working_cues, working_images, _, subchannels = (
            popfe.prepare_target_inputs(
                request.plan,
                request.cue_files,
                request.image_files,
                request.real_disc_ids,
                request.work_dir,
                undither=request.undither,
                sbi_files=request.sbi_files,
            )
        )

        set_phase('Processing audio...')
        aea_files, _ = popfe.generate_aea_files(
            working_cues,
            working_images,
            request.work_dir,
        )
        planned_configs = read_planned_configs(
            request.plan,
            force_ntsc=False,
            cdda=False,
        )
        expectation = self._build_eboot_expectation(
            request,
            working_cues,
            working_images,
            subchannels,
        )
        return PreparedPspConversion(
            cue_files=tuple(working_cues),
            image_files=tuple(working_images),
            audio_files=tuple(aea_files),
            subchannels=tuple(subchannels),
            planned_configs=tuple(planned_configs),
            sound=sound,
            manual=manual,
            logo=logo,
            expectation=expectation,
        )

    def _write_psp_eboot(self, request, prepared):
        return Path(
            popfe.create_psp(
                request.output_dir,
                request.disc_ids,
                request.real_disc_ids,
                request.title,
                request.icon0,
                None if request.disable_pic0 else request.pic0,
                None if request.disable_pic1 else request.pic1,
                prepared.cue_files,
                request.real_cue_files,
                prepared.image_files,
                [],
                prepared.audio_files,
                subdir=request.work_dir,
                snd0=prepared.sound,
                no_pstitleimg=request.disable_title_image,
                watermark=request.watermark,
                subchannels=prepared.subchannels,
                manual=prepared.manual,
                use_cdda=request.use_cdda,
                logo=prepared.logo,
                no_libcrypt=True,
                psx_undither=False,
                force_ntsc=request.force_ntsc,
                cdda=request.use_cdda,
                planned_configs=prepared.planned_configs,
                compression_level=request.plan.compression_level,
            )
        )

    def _validate_psp_eboot(self, request, prepared, output_path):
        report_path = output_path.with_name('PSXFoundry-report.txt')
        validation = validate_generated_eboot(
            output_path,
            prepared.expectation,
            report_path=report_path,
        )
        report = render_target_workflow_report(request.plan)
        override_lines = [
            '- Manual settings: ' + ', '.join(request.manual_overrides)
        ] if request.manual_overrides else []
        if request.disc_ids != request.plan.output_disc_ids:
            override_lines.append('- Disc IDs: ' + ', '.join(request.disc_ids))
        overrides = 'Overrides:\n' + '\n'.join(
            override_lines or ['- None']
        ) + '\n'
        protection_lines = []
        for index, (disc, origin, data) in enumerate(
            zip(request.plan.discs, request.sbi_origins, prepared.subchannels),
            start=1,
        ):
            if origin:
                protection_lines.append(f'- Disc {index}: SBI ({origin})')
            elif disc.libcrypt_magic_word is not None and data is not None:
                protection_lines.append(
                    f'- Disc {index}: generated LibCrypt fallback'
                )
        protection = (
            'Protection data:\n' + '\n'.join(protection_lines) + '\n'
            if protection_lines
            else ''
        )
        report_path.write_text(
            report + overrides + protection + validation.to_text(),
            encoding='utf-8',
        )
        if not validation.ok:
            raise RuntimeError(
                'EBOOT validation failed. See ' + str(report_path)
            )

    def _create_eboot(self, request, set_phase):
        print('Creating EBOOT')
        print('DISC', request.disc_ids[0])
        print('TITLE', request.title)
        prepared = self._prepare_psp_conversion(request, set_phase)
        set_phase('Creating EBOOT.PBP...')
        output_path = self._write_psp_eboot(request, prepared)
        set_phase('Validating EBOOT.PBP...')
        self._validate_psp_eboot(request, prepared, output_path)
        return output_path

    def _finish_eboot_conversion(self, output_path):
        dialog = CompletionDialog(
            self.master,
            'Finished creating EBOOT\n' + str(output_path),
        )
        self.master.wait_window(dialog)
        self.init_data()

    def _confirm_generated_sbi_fallback(self, plan):
        missing = [
            index
            for index, (disc, selection) in enumerate(
                zip(plan.discs, self.sbi_selections),
                start=1,
            )
            if disc.libcrypt_magic_word and selection is None
        ]
        if not missing:
            return True
        discs = ', '.join(str(index) for index in missing)
        details = [
            self.sbi_errors[index - 1]
            for index in missing
            if self.sbi_errors[index - 1]
        ]
        message = (
            f'No verified SBI file is available for disc {discs}.\n\n'
            'PSXFoundry can use generated LibCrypt data, but it may not '
            'match the original disc. The game could hang or crash.\n\n'
            'Continue with the generated fallback?'
        )
        if details:
            message += '\n\nLookup result: ' + details[0]
        return messagebox.askyesno(
            'LibCrypt SBI missing',
            message,
            parent=self.master,
        )

    def on_create_eboot(self):
        if not self.cue_files:
            return
        if self.conversion_task is not None and self.conversion_task.running:
            return

        try:
            plan = (
                self.conversion_plan
                or self._refresh_conversion_plan_with_prompt()
            )
            if plan is None:
                return
            if not self._confirm_generated_sbi_fallback(plan):
                return
            request = self._build_conversion_request(plan)
        except Exception as error:
            show_conversion_error(
                self.master,
                popfe_runtime,
                'psp',
                'Could not create EBOOT',
                error,
            )
            return

        self.conversion_task = ConversionTask(
            self.master,
            popfe_runtime,
            'psp',
            'Could not create EBOOT',
            lambda set_phase: self._create_eboot(request, set_phase),
            self._finish_eboot_conversion,
        )
        self.conversion_task.start()

    def on_cdda(self):
        self.cdda = self.builder.get_variable('cdda_variable').get()
        self._mark_advanced_override('cdda')

    def on_force_ntsc(self):
        self._mark_advanced_override('force_ntsc')

    def on_psx_undither(self):
        self._mark_advanced_override('undither')

    def on_ntsc_u_icon0(self):
        self._mark_advanced_override('ntsc_u_icon0')
        self.update_assets(update_pic0=False, update_pic1=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', action='store_true', help='Verbose')
    args = parser.parse_args()

    if args.v:
        verbose = True

    smoke_test = os.environ.get(
        "PSXFOUNDRY_GUI_SMOKE_TEST",
        os.environ.get("POPFE_GUI_SMOKE_TEST"),
    ) == "1"
    root = tk.Tk()
    if smoke_test:
        root.withdraw()
    if popfe_runtime.is_macos:
        install_tk_error_handler(
            root, popfe_runtime, "psp", "PSXFoundry PSP Error"
        )
    app = PspApp(root)
    root.title('PSXFoundry PSP')
    root.minsize(1040, 680)
    root.rowconfigure(0, weight=1)
    root.columnconfigure(0, weight=1)
    app.mainwindow.columnconfigure(0, weight=1)
    app.mainwindow.columnconfigure(1, weight=1)
    if smoke_test:
        import_directory = os.environ.get(
            'PSXFOUNDRY_GUI_IMPORT_FOLDER',
            os.environ.get('POPFE_GUI_IMPORT_FOLDER'),
        )
        if import_directory:
            result = app.import_folder(
                import_directory,
                import_all_discs=(
                    os.environ.get(
                        'PSXFOUNDRY_GUI_IMPORT_ALL_DISCS',
                        os.environ.get('POPFE_GUI_IMPORT_ALL_DISCS', '1'),
                    ) != '0'
                ),
            )
            print(
                'Imported %d disc(s): %s; %s'
                % (
                    len(result.discs),
                    result.fallback_title,
                    app.builder.get_variable('import_summary_variable').get(),
                )
            )
        root.update_idletasks()
        root.destroy()
    else:
        root.mainloop()
    
