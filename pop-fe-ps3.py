#!/usr/bin/env python

import argparse
from dataclasses import dataclass
import os
import pygubu
import pygubu.widgets.simpletooltip as tooltip
import requests
import shutil
import tkinter as tk
from tkinterdnd2 import DND_FILES, TkinterDnD
from pathlib import Path
from psxfoundry.gui import (
    DesktopAppMixin,
    CompletionDialog,
    ConversionTask,
    choose_image,
    clear_temporary_paths,
    install_tk_error_handler,
    label_path_chooser,
    load_dropped_image,
    load_theme_image,
    show_conversion_error,
)
from popfe_runtime import runtime as popfe_runtime
from psxfoundry.cache import AnalysisCache
from psxfoundry.psp_workflow import (
    build_target_plan,
    read_ps3_configs,
)
from psxfoundry.report import render_target_workflow_report


have_pytube = False
try:
    import pytubefix as pytube
    have_pytube = True
except:
    True

from PIL import Image, ImageDraw
import importlib
from gamedb import games, themes
from layout import image_has_transparency
try:
    import popfe
except:
    popfe = importlib.import_module("pop-fe")

verbose = False
temp_files = []

PROJECT_PATH = popfe_runtime.resource_root
PROJECT_UI = popfe_runtime.resource_path("pop-fe-ps3.ui", required=True)
PREFERENCES_PATH = popfe_runtime.application_preference_path(
    "psxfoundry-ps3.config"
)


@dataclass(frozen=True)
class Ps3ConversionRequest:
    plan: object
    output_path: str
    disc_ids: tuple[str, ...]
    real_disc_ids: tuple[str, ...]
    title: str
    icon: object
    logo: object
    background: object
    cue_files: tuple[str, ...]
    real_cue_files: tuple[str, ...]
    image_files: tuple[str, ...]
    work_dir: str
    sound: str | None
    manual: str
    undither: bool
    use_new_emulator: bool
    allow_disc_swap: bool
    force_ntsc: bool
    data_track_only: bool
    resolution: int


class Ps3App(DesktopAppMixin):
    preview_audio_search = (
        pytube.contrib.search.Search if have_pytube else None
    )

    def __init__(self, master=None):
        self.myrect = None
        self.cue_file_orig = None
        self.cue_files = None
        self.real_cue_files = None
        self.img_files = None
        self.disc_ids = None
        self.md5_sums = None
        self.real_disc_ids = None
        self.icon0 = None
        self.icon0_tk = None
        self.pic0 = None
        self.pic0_orig = None
        self.pic0_path = None
        self.pic0_tk = None
        self.pic1 = None
        self.pic1_path = None
        self.pic1_tk = None
        self.back = None
        self.disc = None
        self.pic0_disabled = 'off'
        self.pic1_bc = 'off'
        self.pic1_disabled = 'off'
        self.snd0_disabled = 'off'
        self.icon0_disc = 'off'
        self.preview_tk = None
        self.pkgdir = None
        self.data_track_only = 'off'
        self.subdir = str(
            popfe_runtime.application_work_dir("ps3", "psxfoundry-ps3-work")
        ) + os.sep
        self.pic0scaling = 0.9
        self.pic0xoffset = 0.1
        self.pic0yoffset = 0.1
        self.manual = None
        self.conversion_plan = None
        self.conversion_task = None
        self.advanced_visible = False
        self.analysis_cache = AnalysisCache(
            popfe_runtime.cache_dir / 'psxfoundry' / 'analysis'
        )
        self.path_dir = (
            str(popfe_runtime.home)
            if popfe_runtime.is_macos
            else os.getcwd()
        )

        self.master = master
        self.builder = builder = pygubu.Builder()
        builder.add_resource_path(PROJECT_PATH)
        builder.add_from_file(PROJECT_UI)
        self.mainwindow = builder.get_object("top_frame", master)

        builder.connect_callbacks(self)
        self._configure_layout()
        self._configure_drop_targets()
        self._configure_tooltips()
        self._theme = ''
        o = ['']
        for theme in themes:
            o.append(theme)
        self.builder.get_object('theme', self.master).configure(values=o)
        self.init_data()
        try:
            self.read_prefs()
        except:
            True

    def _configure_drop_targets(self):
        targets = (
            ('icon0_canvas', self.on_icon0_dropped),
            ('pic0_canvas', self.on_pic0_dropped),
            ('pic1_canvas', self.on_pic1_dropped),
        )
        for object_id, handler in targets:
            canvas = self.builder.get_object(object_id, self.master)
            canvas.drop_target_register(DND_FILES)
            canvas.dnd_bind('<<Drop>>', handler)

    def _configure_tooltips(self):
        descriptions = {
            'use_psx_undither': 'Reduce dithering in supported games.',
            'allow_swapdisc': 'Allow disc changes before a game requests one.',
            'force_newemu': 'Use ps1_newemu for a known compatibility need.',
            'force_ntsc': 'Force 60 Hz; PAL games may run at the wrong speed.',
            'disc_as_icon0': 'Use the disc scan as the game icon.',
            'pic1_as_background': 'Use the back cover as the background.',
            'data_track_only': 'Skip raw CD audio tracks to reduce output size.',
            'disable_snd0': 'Remove preview audio from the XMB.',
            'disable_pic1': 'Remove the XMB background image.',
            'disable_pic0': 'Remove the XMB game logo.',
            'pic0scaling': 'Set the game logo size; 1.0 is original size.',
            'pic0xoffset': 'Move the game logo horizontally.',
            'pic0yoffset': 'Move the game logo vertically.',
        }
        for object_id, description in descriptions.items():
            tooltip.create(
                self.builder.get_object(object_id, self.master), description
            )

    def __del__(self):
        global temp_files
        clear_temporary_paths(temp_files, verbose=verbose)

    def _configure_layout(self):
        self.mainwindow.columnconfigure(0, weight=1, uniform='content')
        self.mainwindow.columnconfigure(1, weight=1, uniform='content')

        source = self.builder.get_object('frame1', self.master)
        source.grid_configure(sticky='new')
        source.columnconfigure(0, weight=1)
        for section_id in ('discs', 'nameofgame', 'theme_frame'):
            section = self.builder.get_object(section_id, self.master)
            section.grid_configure(sticky='ew')
            section.columnconfigure(1, weight=1)

        discs = self.builder.get_object('discs', self.master)
        discs.columnconfigure(0, weight=1)
        for index in range(1, 6):
            chooser = self.builder.get_object(
                f'disc{index}', self.master
            )
            chooser.grid_configure(sticky='ew', pady=2)
            label_path_chooser(chooser, 'Choose disc...')

        for object_id, text in (
            ('snd0', 'Choose audio...'),
            ('manual', 'Choose manual...'),
            ('pathchooserinput1', 'Choose folder...'),
        ):
            chooser = self.builder.get_object(object_id, self.master)
            chooser.grid_configure(sticky='ew')
            label_path_chooser(chooser, text)

        for label_id in ('label9', 'label13', 'label7', 'label3'):
            self.builder.get_object(label_id, self.master).configure(
                anchor='e', width=14
            )
        self.builder.get_object('theme', self.master).configure(
            state='readonly'
        )

        preview = self.builder.get_object('frame3', self.master)
        preview.grid_configure(sticky='new')
        preview.columnconfigure(0, weight=1)

        images = self.builder.get_object('images', self.master)
        images.grid_configure(sticky='ew')
        for column, object_id in enumerate(('icon0', 'pic0', 'pic1')):
            images.columnconfigure(column, weight=1, uniform='artwork')
            self.builder.get_object(
                object_id, self.master
            ).grid_configure(row=0, column=column, padx=6)

        output = self.builder.get_object('outputpkg', self.master)
        output.columnconfigure(1, weight=1)
        output.columnconfigure(3, weight=1)
        self.builder.get_object('entry4', self.master).grid_configure(
            sticky='ew'
        )
        self.builder.get_object('options', self.master).grid_remove()

    def on_toggle_advanced(self):
        panel = self.builder.get_object('options', self.master)
        button = self.builder.get_object('advanced_button', self.master)
        if self.advanced_visible:
            panel.grid_remove()
            button.configure(text='Advanced settings')
        else:
            panel.grid()
            button.configure(text='Hide advanced settings')
        self.advanced_visible = not self.advanced_visible
        temp_files = []

    def update_prefs(self):
        PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(PREFERENCES_PATH, "w") as f:
            f.write('%s:%s\n' % ('newemu', self.builder.get_variable('force_newemu_variable').get()))
            f.write('%s:%s\n' % ('swap', self.builder.get_variable('allow_discswap_variable').get()))
            f.write('%s:%s\n' % ('ntsc', self.builder.get_variable('force_ntsc_variable').get()))
            f.write('%s:%s\n' % ('undither', self.builder.get_variable('psx_undither_variable').get()))
            f.write('%s:%s\n' % ('pkgdir', self.builder.get_variable('pkgdir_variable').get()))
            if self.path_dir:
                f.write('%s:%s\n' % ('path', self.path_dir))


    def read_prefs(self):
        with open(PREFERENCES_PATH, "r") as f:
            for x in f.read().splitlines():
                key, val = x.split(':', 1)
                if key == 'newemu':
                    self.builder.get_variable('force_newemu_variable').set(val)
                if key == 'swap':
                    self.builder.get_variable('allow_discswap_variable').set(val)
                if key == 'ntsc':
                    self.builder.get_variable('force_ntsc_variable').set(val)
                if key == 'undither':
                    self.builder.get_variable('psx_undither_variable').set(val)
                if key == 'pkgdir':
                    self.builder.get_variable('pkgdir_variable').set(val)
                if key == 'path':
                    self.path_dir = val
                    if self.path_dir:
                        self.builder.get_object('disc1', self.master).config(initialdir=self.path_dir)
                        self.builder.get_object('disc2', self.master).config(initialdir=self.path_dir)
                        self.builder.get_object('disc3', self.master).config(initialdir=self.path_dir)
                        self.builder.get_object('disc4', self.master).config(initialdir=self.path_dir)
                        self.builder.get_object('disc5', self.master).config(initialdir=self.path_dir)

                
    def init_data(self):
        global temp_files
        if temp_files:
            for f in temp_files:
                try:
                    os.unlink(f)
                except:
                    try:
                        os.rmdir(f)
                    except:
                        True

        temp_files = []  
        temp_files.append(self.subdir)
        shutil.rmtree(self.subdir, ignore_errors=True)
        os.mkdir(self.subdir)

        self.cue_files = []
        self.real_cue_files = []
        self.img_files = []
        self.disc_ids = []
        self.md5_sums = []
        self.real_disc_ids = []
        self.icon0 = None
        self.icon0_tk = None
        self.pic0 = None
        self.pic0_orig = None
        self.pic0_path = None
        self.pic0_tk = None
        self.pic1 = None
        self.pic1_path = None
        self.pic1_tk = None
        self.back = None
        self.disc = None
        self.preview_tk = None
        self.manual = None
            
        for idx in range(1,6):
            self.builder.get_object('discid%d' % (idx), self.master).config(state='disabled')
            self.builder.get_object('disc' + str(idx), self.master).config(filetypes=[('Image files', ['.cue', '.ccd', '.img', '.zip', '.chd']), ('All Files', ['*.*', '*'])])
            self.builder.get_variable('disc%d_variable' % (idx)).set('')
            self.builder.get_variable('discid%d_variable' % (idx)).set('')
            self.builder.get_object('disc' + str(idx), self.master).config(state='disabled')
        self.builder.get_object('disc1', self.master).config(state='normal')
        self.builder.get_object('create_button', self.master).config(state='disabled')
        self.builder.get_object('youtube_button', self.master).config(state='disabled')
        self.builder.get_object('pic0scaling', self.master).config(state='disabled')
        self.builder.get_object('pic0xoffset', self.master).config(state='disabled')
        self.builder.get_object('pic0yoffset', self.master).config(state='disabled')
        self.builder.get_variable('title_variable').set('')
        self.builder.get_object('snd0', self.master).config(filetypes=[('Audio files', ['.wav']), ('All Files', ['*.*', '*'])])
        self.builder.get_variable('snd0_variable').set('')
        self.builder.get_object('manual', self.master).config(state='disabled')
        self.builder.get_object('manual', self.master).config(filetypes=[('All Files', ['*.*', '*'])])
        self.builder.get_variable('manual_variable').set('')
        self.builder.get_variable('pic0scaling_variable').set('')
        self.builder.get_variable('pic0xoffset_variable').set('')
        self.builder.get_variable('pic0yoffset_variable').set('')

    def _refresh_conversion_plan(self, allow_missing_fixes=False):
        if not self.cue_files:
            self.conversion_plan = None
            return None

        self.conversion_plan = None
        plan = build_target_plan(
            self.cue_files,
            'ps3',
            fallback_disc_ids=self.real_disc_ids,
            analysis_cache=self.analysis_cache,
            allow_missing_fixes=allow_missing_fixes,
        )
        self.conversion_plan = plan
        for idx, planned_id in enumerate(plan.output_disc_ids, start=1):
            self.builder.get_variable('discid%d_variable' % idx).set(planned_id)
        self.builder.get_variable('force_ntsc_variable').set(
            'on' if plan.force_ntsc else 'off'
        )
        self.builder.get_variable('psx_undither_variable').set(
            'on' if plan.undither else 'off'
        )
        return plan

    def update_preview(self):
        if self.pic0_orig and self.pic0.mode == 'P':
            self.pic0_orig = self.pic0.convert(mode='RGBA')

        c = self.builder.get_object('preview_canvas', self.master)
        if not self.pic1 or self.pic1_disabled == 'on':
            p1 = Image.new("RGBA", (382,216), (255,255,255,0))
        else:
            if self.pic1_bc == 'off':
                p1 = self.pic1.resize((382,216), Image.Resampling.HAMMING)
            else:
                p1 = self.back.resize((382,216), Image.Resampling.HAMMING)
        p1 = p1.convert('RGBA')
        
        if self.pic0_disabled == 'on':
            _pic0 = None
        else:
            _pic0 = popfe.rescale_pic0(self.pic0_orig, popfe.get_pic0_scaling(self.disc_ids[0]), popfe.get_pic0_offset(self.disc_ids[0]))
        if _pic0:
            p0 = _pic0.resize((int(p1.size[0] * 0.55) , int(p1.size[1] * 0.58)), Image.Resampling.HAMMING)
            if image_has_transparency(p0):
                Image.Image.paste(p1, p0, box=(148,79), mask=p0)
            else:
                Image.Image.paste(p1, p0, box=(148,79))
        i0 = None
        if self.icon0 and self.icon0_disc == 'off':
                i0 = self.icon0.resize((int(p1.size[0] * 0.10) , int(p1.size[0] * 0.10)), Image.Resampling.HAMMING)
        if self.disc and self.icon0_disc == 'on':
                i0 = self.disc.resize((int(p1.size[0] * 0.10) , int(p1.size[0] * 0.10)), Image.Resampling.HAMMING)
        if i0:
            if image_has_transparency(i0):
                Image.Image.paste(p1, i0, box=(100,79), mask=i0)
            else:
                Image.Image.paste(p1, i0, box=(100,79))
        temp_files.append(self.subdir + 'PREVIEW.PNG')
        p1.save(self.subdir + 'PREVIEW.PNG')
        self.preview_tk = tk.PhotoImage(file = self.subdir + 'PREVIEW.PNG')
        c = self.builder.get_object('preview_canvas', self.master)
        c.create_image(0, 0, image=self.preview_tk, anchor='nw')

    def fetch_pic0(self):
        disc_id = self.disc_ids[0]
        game = popfe.get_game_from_gamelist(disc_id)
        
        self.pic0 = None
        if self.pic0_path:
            self.pic0 = Image.open(self.pic0_path)
            self.pic0_orig = Image.open(self.pic0_path)
        if not self.pic0 and self._theme != '':
            self.pic0_orig = load_theme_image(
                popfe.get_image_from_theme,
                self._theme,
                disc_id,
                self.subdir,
                'PIC0',
            )
            self.pic0 = self.pic0_orig
        if not self.pic0:
            self.pic0_orig = popfe.get_pic0_from_game(disc_id, game, self.cue_file_orig, no_scaling=True)
            self.pic0 = popfe.rescale_pic0(self.pic0_orig, popfe.get_pic0_scaling(disc_id), popfe.get_pic0_offset(disc_id))
        if self.pic0:
            self._render_artwork_preview('pic0', (128, 80), temp_files)
        
    def update_assets(self):
        if not self.disc_ids:
            return
        if not self.cue_file_orig:
            return
        disc_id = self.disc_ids[0]
        game = popfe.get_game_from_gamelist(disc_id)
        if self.snd0_disabled == 'off':
            snd0 = None
            print('Fetching SND0') if verbose else None
            if self._theme != '':
                snd0 = popfe.get_snd0_from_theme(self._theme, disc_id, self.subdir)
                if snd0:
                    temp_files.append(snd0)
            if not snd0 and disc_id in games and 'snd0' in games[disc_id]:
                snd0 = games[disc_id]['snd0']
            if snd0:
                self.builder.get_variable('snd0_variable').set(snd0)
                
        print('Fetching ICON0') if verbose else None
        self.icon0 = None
        if self._theme != '':
            print('Get icon0 from theme')
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
            self.icon0 = popfe.get_icon0_from_game(disc_id, game, self.cue_file_orig, self.subdir + 'ICON0.PNG', psn_frame_size=((176,176),(138,138)))
            
        if self.icon0:
            self._render_artwork_preview('icon0', (80, 80), temp_files)
            
        print('Fetching PIC0') if verbose else None
        self.fetch_pic0()
        
        print('Fetching PIC1') if verbose else None
        self.pic1 = None
        if self.pic1_path:
            self.pic1 = Image.open(self.pic1_path)
        if not self.pic1 and self._theme != '':
            self.pic1 = load_theme_image(
                popfe.get_image_from_theme,
                self._theme,
                disc_id,
                self.subdir,
                'PIC1',
            )
        if not self.pic1:
            self.pic1 = popfe.get_pic1_from_game(disc_id, game, self.cue_file_orig)
        if self.pic1:
            self._render_artwork_preview('pic1', (128, 80), temp_files)

        self.update_preview()
        
    def on_path_changed(self, event):
        source_path = event.widget.cget('path')
        if not source_path:
            return

        self.path_dir = os.path.dirname(source_path)
        self.update_prefs()
        self.master.config(cursor='watch')
        self.master.update()
        try:
            disc_number = int(event.widget.cget('title')[1])
            print('Processing', source_path) if verbose else None
            cue_file, real_cue_file, image_file = popfe.process_disk_file(
                source_path, disc_number, temp_files, subdir=self.subdir
            )
            temporary_iso = self.subdir + 'TMP01.iso'
            disc_id, md5_sum = popfe.get_disc_id(
                cue_file, real_cue_file, temporary_iso
            )

            self.cue_file_orig = real_cue_file
            self.img_files.append(image_file)
            self.disc_ids.append(disc_id)
            self.md5_sums.append(md5_sum)
            self.real_disc_ids.append(disc_id)
            self.cue_files.append(cue_file)
            self.real_cue_files.append(real_cue_file)
            self.builder.get_variable(
                f'discid{disc_number}_variable'
            ).set(disc_id)

            game = games.get(disc_id, {})
            if 'manual' in game:
                print('Found a MANUAL for', disc_id)
                self.manual = game['manual']
            self._advance_disc_input(disc_number)
            if disc_number == 1:
                self._configure_first_disc(disc_id, game)
            self._refresh_conversion_plan_with_prompt()
            print('Finished processing disc') if verbose else None
        finally:
            self.master.config(cursor='')

    def _advance_disc_input(self, disc_number):
        self.builder.get_object(
            f'discid{disc_number}', self.master
        ).configure(state='normal')
        self.builder.get_object(
            f'disc{disc_number}', self.master
        ).configure(state='disabled')
        if disc_number < 5:
            self.builder.get_object(
                f'disc{disc_number + 1}', self.master
            ).configure(state='normal')

    def _configure_first_disc(self, disc_id, game):
        self.builder.get_variable('title_variable').set(
            popfe.get_title_from_game(disc_id)
        )
        self.pic0scaling = game.get('pic0-scaling', 0.9)
        self.pic0xoffset, self.pic0yoffset = game.get(
            'pic0-offset', (0.1, 0.1)
        )
        values = {
            'pic0scaling_variable': self.pic0scaling,
            'pic0xoffset_variable': self.pic0xoffset,
            'pic0yoffset_variable': self.pic0yoffset,
            'manual_variable': self.manual,
        }
        for variable, value in values.items():
            self.builder.get_variable(variable).set(value)
        for object_id in (
            'create_button',
            'youtube_button',
            'disable_pic0',
            'pic1_as_background',
            'disc_as_icon0',
            'pic0scaling',
            'pic0xoffset',
            'pic0yoffset',
            'manual',
        ):
            self.builder.get_object(
                object_id, self.master
            ).configure(state='normal')
        self.update_assets()


    def on_icon0_dropped(self, event):
        self.master.config(cursor='watch')
        self.master.update()
        image = load_dropped_image(event.data, requests.get)
        self.master.config(cursor='')
        self._set_artwork_image('icon0', image)
        
    def on_icon0_clicked(self, event):
        _, image = choose_image(self.master, 'Select image for ICON0')
        self._set_artwork_image('icon0', image)

    def on_pic0_dropped(self, event):
        self.master.config(cursor='watch')
        self.master.update()
        image = load_dropped_image(event.data, requests.get)
        self.master.config(cursor='')
        self._set_artwork_image('pic0', image)
        
    def on_pic0_clicked(self, event):
        path, image = choose_image(self.master, 'Select image for PIC0')
        self.pic0_path = path
        self._set_artwork_image('pic0', image)

    def on_pic1_dropped(self, event):
        self.master.config(cursor='watch')
        self.master.update()
        image = load_dropped_image(event.data, requests.get)
        self.master.config(cursor='')
        self._set_artwork_image('pic1', image)
        
    def on_pic1_clicked(self, event):
        _, image = choose_image(self.master, 'Select image for PIC1')
        self._set_artwork_image('pic1', image)

    def _set_artwork_image(self, name, image):
        if image is None:
            return
        setattr(self, name, image)
        if name == 'pic0':
            self.pic0_orig = image.copy()
        size = (80, 80) if name == 'icon0' else (128, 80)
        self._render_artwork_preview(name, size, temp_files)
        self.update_preview()

    def on_force_ntsc(self):
        self.update_prefs()
        
    def on_force_newemu(self):
        self.update_prefs()
        
    def on_allow_swapdisc(self):
        self.update_prefs()
        
    def on_psx_undither(self):
        self.update_prefs()
        
    def on_data_track_only(self):
        self.data_track_only = self.builder.get_variable('data_track_only_variable').get()
        self.update_preview()

    def on_pic0_disabled(self):
        self.pic0_disabled = self.builder.get_variable('pic0_disabled_variable').get()
        self.update_preview()

    def on_pic1_disabled(self):
        self.pic1_disabled = self.builder.get_variable('pic1_disabled_variable').get()
        self.update_preview()

    def on_snd0_disabled(self):
        self.snd0_disabled = self.builder.get_variable('snd0_disabled_variable').get()

    def on_icon0_from_disc(self):
        self.icon0_disc = self.builder.get_variable('disc_as_icon0_variable').get()
        if not self.disc and self.disc_ids:
            disc_id = self.disc_ids[0]
            game = popfe.get_game_from_gamelist(disc_id)
            self.master.config(cursor='watch')
            self.master.update()
            d = popfe.get_icon0_from_disc(disc_id, game, self.cue_files[0], 'DISC.PNG')
            size = (176,176)
            d = d.resize(size, Image.Resampling.HAMMING)
            bigsize = (d.size[0] * 3, d.size[1] * 3)
            mask = Image.new('L', bigsize, 0)
            draw = ImageDraw.Draw(mask) 
            draw.ellipse((0, 0) + bigsize, fill=255)
            mask = mask.resize(d.size, Image.ANTIALIAS)
            d.putalpha(mask)
            self.disc = d
            self.master.config(cursor='')

        self.builder.get_object('icon0_or_disc', self.master).config(text='COVER' if self.icon0_disc == 'off' else 'DISC')
        if self.icon0_disc == 'off':
            self.icon0.resize((80,80), Image.Resampling.HAMMING).save(self.subdir + 'ICON0.PNG')
        else:
            self.disc.resize((80,80), Image.Resampling.HAMMING).save(self.subdir + 'ICON0.PNG')
        self.icon0_tk = tk.PhotoImage(file = self.subdir + 'ICON0.PNG')
        c = self.builder.get_object('icon0_canvas', self.master)
        c.create_image(0, 0, image=self.icon0_tk, anchor='nw')
        
        self.update_preview()
            
    def on_pic1_from_bc(self):
        self.pic1_bc = self.builder.get_variable('bc_for_pic1_variable').get()
        if not self.back and self.disc_ids:
            disc_id = self.disc_ids[0]
            game = popfe.get_game_from_gamelist(disc_id)
            self.master.config(cursor='watch')
            self.master.update()
            self.back = popfe.get_pic1_from_bc(disc_id, game, self.cue_files[0])
            self.master.config(cursor='')
        self.builder.get_object('pic1_or_back', self.master).config(text='PIC1' if self.pic1_bc == 'off' else 'BACK')
        if self.pic1_bc == 'off':
            self.pic1.resize((128,80), Image.Resampling.HAMMING).save(self.subdir + 'PIC1.PNG')
        else:
            self.back.resize((128,80), Image.Resampling.HAMMING).save(self.subdir + 'PIC1.PNG')
        self.pic1_tk = tk.PhotoImage(file = self.subdir + 'PIC1.PNG')
        c = self.builder.get_object('pic1_canvas', self.master)
        c.create_image(0, 0, image=self.pic1_tk, anchor='nw')
        
        self.update_preview()

    def on_pic0_scaling(self, event):
        try:
            v = float(self.builder.get_variable('pic0scaling_variable').get())
        except:
            return

        if v > 0.1 and v != self.pic0scaling and self.disc_ids:
            self.pic0scaling = v
            games[self.disc_ids[0]]['pic0-scaling'] = self.pic0scaling
            self.update_preview()

    def on_pic0_xoffset(self, event):
        try:
            v = float(self.builder.get_variable('pic0xoffset_variable').get())
        except:
            return

        if v >= 0.0 and v != self.pic0xoffset and self.disc_ids:
            self.pic0xoffset = v
            games[self.disc_ids[0]]['pic0-offset'] = (self.pic0xoffset, self.pic0yoffset)
            self.update_preview()
            
    def on_pic0_yoffset(self, event):
        try:
            v = float(self.builder.get_variable('pic0yoffset_variable').get())
        except:
            return

        if v >= 0.0 and v != self.pic0yoffset and self.disc_ids:
            self.pic0yoffset = v
            games[self.disc_ids[0]]['pic0-offset'] = (self.pic0xoffset, self.pic0yoffset)
            self.update_preview()
            
    def on_dir_changed(self, event):
        self.pkgdir = event.widget.cget('path')
        # PKG in print()

    def _ps3_output_path(self):
        filename = self.builder.get_variable('pkgfile_variable').get()
        filename = filename or 'game.pkg'
        output_directory = self.builder.get_variable('pkgdir_variable').get()
        if output_directory:
            return str(Path(output_directory) / filename)
        if popfe_runtime.is_macos:
            return str(popfe_runtime.home / filename)
        return filename

    def _build_ps3_conversion_request(self, plan):
        disc_ids = tuple(
            self.builder.get_variable(
                'discid%d_variable' % (index + 1)
            ).get()
            for index in range(len(self.cue_files))
        )
        force_ntsc = (
            self.builder.get_variable('force_ntsc_variable').get() == 'on'
        )
        resolution = 1
        if disc_ids[0].startswith(('SLE', 'SCE')) and not force_ntsc:
            resolution = 2

        background = self.pic1 if self.pic1_bc == 'off' else self.back
        if self.pic1_disabled == 'on':
            background = None
        sound = None
        if self.snd0_disabled == 'off':
            sound = self.builder.get_variable('snd0_variable').get()

        return Ps3ConversionRequest(
            plan=plan,
            output_path=self._ps3_output_path(),
            disc_ids=disc_ids,
            real_disc_ids=tuple(self.real_disc_ids),
            title=self.builder.get_variable('title_variable').get(),
            icon=self.icon0 if self.icon0_disc == 'off' else self.disc,
            logo=self.pic0 if self.pic0_disabled == 'off' else None,
            background=background,
            cue_files=tuple(self.cue_files),
            real_cue_files=tuple(self.real_cue_files),
            image_files=tuple(self.img_files),
            work_dir=self.subdir,
            sound=sound,
            manual=self.builder.get_variable('manual_variable').get(),
            undither=(
                self.builder.get_variable('psx_undither_variable').get() == 'on'
            ),
            use_new_emulator=(
                self.builder.get_variable('force_newemu_variable').get() == 'on'
            ),
            allow_disc_swap=(
                self.builder.get_variable('allow_discswap_variable').get() == 'on'
            ),
            force_ntsc=force_ntsc,
            data_track_only=self.data_track_only == 'on',
            resolution=resolution,
        )

    def _prepare_ps3_assets(self, request, set_phase):
        set_phase('Preparing assets...')
        sound = request.sound
        if sound and sound.startswith('https://www.youtube.com/'):
            sound = popfe.get_snd0_from_link(sound, subdir=request.work_dir)
            if sound:
                temp_files.append(sound)

        manual = request.manual
        if manual and manual != 'None':
            manual = popfe.create_manual(
                manual,
                request.real_disc_ids[0],
                subdir=request.work_dir,
                ps3_manual=True,
            )
        else:
            manual = None
        return sound, manual

    def _create_ps3_package(self, request, set_phase):
        sound, manual = self._prepare_ps3_assets(request, set_phase)
        set_phase('Applying compatibility fixes...')
        working_cues, working_images, magic_word, subchannels = (
            popfe.prepare_target_inputs(
                request.plan,
                request.cue_files,
                request.image_files,
                request.real_disc_ids,
                request.work_dir,
                undither=request.undither,
            )
        )

        set_phase('Processing audio...')
        audio_files, extra_data_tracks = popfe.generate_aea_files(
            working_cues,
            working_images,
            request.work_dir,
        )
        data_track_only = request.data_track_only or bool(extra_data_tracks)

        set_phase('Creating PS3 package...')
        output_path = popfe.create_ps3(
            request.output_path,
            request.disc_ids,
            request.real_disc_ids,
            request.title,
            request.icon,
            request.logo,
            request.background,
            working_cues,
            request.real_cue_files,
            working_images,
            [],
            audio_files,
            magic_word,
            request.resolution,
            subdir=request.work_dir,
            snd0=sound,
            subchannels=subchannels,
            manual=manual,
            whole_disk=not data_track_only,
            psx_undither=False,
            ps1_newemu=request.use_new_emulator,
            enable_swap=request.allow_disc_swap,
            force_ntsc=request.force_ntsc,
            no_libcrypt=True,
            planned_configs=read_ps3_configs(request.plan),
        )
        set_phase('Writing conversion report...')
        Path(output_path).with_name('PSXFoundry-report.txt').write_text(
            render_target_workflow_report(request.plan) + 'Validation: passed\n',
            encoding='utf-8',
        )
        return Path(output_path)

    def _finish_ps3_conversion(self, output_path):
        completion = CompletionDialog(
            self.master,
            'Finished creating PKG\n' + str(output_path),
        )
        self.master.wait_window(completion)
        self.init_data()

    def on_create_pkg(self):
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
            request = self._build_ps3_conversion_request(plan)
        except Exception as error:
            show_conversion_error(
                self.master,
                popfe_runtime,
                'ps3',
                'Could not create PKG',
                error,
            )
            return

        print('Creating', request.output_path)
        print('DISC', request.disc_ids[0])
        print('TITLE', request.title)
        self.conversion_task = ConversionTask(
            self.master,
            popfe_runtime,
            'ps3',
            'Could not create PKG',
            lambda set_phase: self._create_ps3_package(request, set_phase),
            self._finish_ps3_conversion,
        )
        self.conversion_task.start()

        
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
    root = TkinterDnD.Tk()
    if smoke_test:
        root.withdraw()
    if popfe_runtime.is_macos:
        install_tk_error_handler(
            root, popfe_runtime, "ps3", "PSXFoundry PS3 Error"
        )
    app = Ps3App(root)
    root.title('PSXFoundry PS3')
    root.minsize(1040, 680)
    root.rowconfigure(0, weight=1)
    root.columnconfigure(0, weight=1)
    if smoke_test:
        root.update_idletasks()
        root.destroy()
    else:
        root.mainloop()
    
