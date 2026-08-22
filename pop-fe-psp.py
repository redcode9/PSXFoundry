#!/usr/bin/python3
#!/usr/bin/env python

import argparse
import os
import pygubu
import pygubu.widgets.simpletooltip as tooltip
import re
import shutil
import struct
import subprocess
import tkinter as tk
import tkinter.ttk as ttk
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox
from popfe_gui import install_tk_error_handler
from popfe_psp_import import FolderImportError, scan_psp_folder
from popfe_runtime import runtime as popfe_runtime
from psxfoundry.cache import AnalysisCache
from psxfoundry.psp_workflow import (
    build_psp_plan,
    execution_decoded_sizes,
    expected_decoded_hashes,
    read_planned_configs,
    verify_planned_patch_sources,
)
from psxfoundry.report import render_psp_workflow_report
from psxfoundry.validation import EbootExpectation, validate_generated_eboot

have_pytube = False
try:
    import pytubefix as pytube
    have_pytube = True
except:
    True

from PIL import Image
from bchunk import bchunk
import importlib  
from gamedb import games, themes
try:
    import popfe
except:
    popfe = importlib.import_module("pop-fe")
from cue import parse_ccd, ccd2cue, write_cue

verbose = False
temp_files = []

DISC_FILETYPES = [
    ('PlayStation images', '*.cue *.ccd *.chd *.zip *.img *.bin'),
    ('All files', '*'),
]

PROJECT_PATH = popfe_runtime.resource_root
PROJECT_UI = popfe_runtime.resource_path("pop-fe-psp.ui", required=True)
PREFERENCES_PATH = popfe_runtime.application_preference_path(
    "pop-fe-psp.config"
)
TARGET_VALUES = {
    'PSP': 'psp',
    'PS Vita / Adrenaline': 'adrenaline',
}


class FinishedDialog(tk.Toplevel):
    def __init__(self, root):
        tk.Toplevel.__init__(self, root)
        label = tk.Label(self, text="Finished creating EBOOT")
        label.pack(fill="both", expand=True, padx=20, pady=20)

        button = tk.Button(self, text="Continue", command=self.destroy)
        button.pack(side="bottom")

class PopFePs3App:
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
        self.pkgdir = None
        self.watermark = 'on'
        self.nopstitleimg = 'off'
        self.pic1aslogo = 'off'
        self.cdda = 'off'
        self.pic0_disabled = 'off'
        self.pic1_disabled = 'off'
        self.snd0_disabled = 'off'
        self.subdir = str(
            popfe_runtime.application_work_dir("psp", "pop-fe-psp-work")
        ) + os.sep
        self.pic0scaling = 0.9
        self.pic0xoffset = 0.1
        self.pic0yoffset = 0.1
        self.manual = None
        self.icon0_path = None
        self.snd0_path = None
        self.path_dir = None
        self.conversion_plan = None
        self.advanced_visible = False
        self.analysis_cache = AnalysisCache(
            popfe_runtime.cache_dir / 'psxfoundry' / 'analysis'
        )
        
        self.master = master
        self.builder = builder = pygubu.Builder()
        builder.add_resource_path(PROJECT_PATH)
        builder.add_from_file(PROJECT_UI)
        self.mainwindow = builder.get_object("top_frame", master)

        callbacks = {
            'on_icon0_clicked': self.on_icon0_clicked,
            'on_add_disc': self.on_add_disc,
            'on_import_folder': self.on_import_folder,
            'on_pic0_clicked': self.on_pic0_clicked,
            'on_pic0_disabled': self.on_pic0_disabled,
            'on_pic1_disabled': self.on_pic1_disabled,
            'on_snd0_disabled': self.on_snd0_disabled,
            'on_pic1_clicked': self.on_pic1_clicked,
            'on_path_changed': self.on_path_changed,
            'on_dir_changed': self.on_dir_changed,
            'on_watermark': self.on_watermark,
            'on_nopstitleimg': self.on_nopstitleimg,
            'on_pic1aslogo': self.on_pic1aslogo,
            'on_youtube_audio': self.on_youtube_audio,
            'on_create_eboot': self.on_create_eboot,
            'on_reset': self.on_reset,
            'on_cdda': self.on_cdda,
            'on_theme_selected': self.on_theme_selected,
            'on_force_ntsc': self.on_force_ntsc,
            'on_pic0_scaling': self.on_pic0_scaling,
            'on_pic0_xoffset': self.on_pic0_xoffset,
            'on_pic0_yoffset': self.on_pic0_yoffset,
            'on_psx_undither': self.on_psx_undither,
            'on_ntsc_u_icon0': self.on_ntsc_u_icon0,
            'on_target_selected': self.on_target_selected,
            'on_toggle_advanced': self.on_toggle_advanced,
        }

        builder.connect_callbacks(callbacks)
        self.builder.get_variable('import_all_discs_variable').set('on')
        self.builder.get_object('target', self.master).configure(
            values=tuple(TARGET_VALUES),
            state='readonly',
        )
        self.builder.get_variable('target_variable').set('PSP')
        self.builder.get_object('frame4', self.master).grid_remove()
        for object_id in ('discs', 'separator5', 'frame1'):
            self.builder.get_object(object_id, self.master).pack_configure(fill='x')
        self.builder.get_object('output_frame', self.master).columnconfigure(
            1, weight=1
        )

        # Tooltips
        self.use_psx_undither = builder.get_object("use_psx_undither")
        tooltip.create(self.use_psx_undither, "Use PSX-Undither to patch the game.\nThis will remove dithering effects.")
        self.pic1aslogo = builder.get_object("pic1aslogo")
        tooltip.create(self.pic1aslogo , "Use pic1 as the LOGO instead of the default P.O.P.S logo")
        self.nopstitleimg = builder.get_object("nopstitleimg")
        tooltip.create(self.nopstitleimg , "Disable the use of PSTITLEIMG for single disc games.\nDo not use unless you know what this means.")
        self.force_ntsc = builder.get_object("force_ntsc")
        tooltip.create(self.force_ntsc , "Encode this game as NTSC even if it is actually PAL")
        self.use_cdda = builder.get_object("use_cdda")
        tooltip.create(self.use_cdda , "Use CDDA audio instead of the default ATRAC3 audio.\nDo not use this unless you need to as it reduces compatibility.\nV-Rally 2 needs this option.")
        self.watermark = builder.get_object("watermark")
        tooltip.create(self.watermark , "Put a small watermark containing the disc-id in the background image")
        self.disable_snd0 = builder.get_object("disable_snd0")
        tooltip.create(self.disable_snd0 , "Disable the SND0 audio that would play when the game icon is\nhighlighted on the XMB")
        self.disable_pic1 = builder.get_object("disable_pic1")
        tooltip.create(self.disable_pic1 , "Disable the background image that would show up on the XMB\nwhen the gameicon is highlighted")
        self.disable_pic0 = builder.get_object("disable_pic0")
        tooltip.create(self.disable_pic0 , "Disable the game logo that would show up on the XMB\nwhen the gameicon is highlighted")
        self.pic0scaling = builder.get_object("pic0scaling")
        tooltip.create(self.pic0scaling , "Change the scaling of the game logo.\n1.0 is 100% of original.\n0.5 is 50%, etc.")
        self.pic0xoffset = builder.get_object("pic0xoffset")
        tooltip.create(self.pic0xoffset , "Shift the placement of pic0 horizontally.\n0.1 means shift 10% to the right.\n-0.1 means shift 10% to the left.\nThe resulting image is bounded by the maximum size of the pic0 box.")
        self.pic0yoffset = builder.get_object("pic0yoffset")
        tooltip.create(self.pic0yoffset , "Shift the placement of pic0 vertically.\n0.1 means shift 10% down.\n-0.1 means shift 10% up.\nThe resulting image is bounded by the maximum size of the pic0 box.")
        self.ntsc_u_icon0 = builder.get_object("ntsc_u_icon0")
        tooltip.create(self.ntsc_u_icon0, "Use a NTSC-U PSN style frame for ICON0.\nThis has a thicker left edge with the text \"Playstation\" running along it\nand requires specially cropped covers to be manuallt provided for ICON0.\nPlease crop a cover image to 60x67 pixels and select it by clicking the ICON0 widget.")
        #self. = builder.get_object("")
        #tooltip.create(self. , "")
        
        
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

    def __del__(self):
        global temp_files
        print('Delete temporary files') if verbose else None
        for f in temp_files:
            print('Deleting temp/dir file', f) if verbose else None
            try:
                os.unlink(f)
            except:
                try:
                    os.rmdir(f)
                except:
                    True
        temp_files = []  

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
        self.preview_tk = None
        self.manual = None
        self.icon0_path = None
        self.snd0_path = None
        for idx in range(1,6):
            self.builder.get_object('discid%d' % (idx), self.master).config(state='disabled')
            self.builder.get_object('disc' + str(idx), self.master).config(filetypes=[('Image files', ['.cue', '.ccd', '.img', '.zip', '.chd']), ('All Files', ['*.*', '*'])])
            self.builder.get_variable('disc%d_variable' % (idx)).set('')
            self.builder.get_variable('discid%d_variable' % (idx)).set('')
            self.builder.get_object('disc' + str(idx), self.master).config(state='disabled')
            self.builder.get_object('disc' + str(idx), self.master).grid_remove()
            self.builder.get_object('discid%d' % (idx), self.master).grid_remove()
        self.builder.get_object('add_disc_button', self.master).config(state='normal')
        self.builder.get_object('create_button', self.master).config(state='disabled')
        self.builder.get_object('youtube_button', self.master).config(state='disabled')
        self.builder.get_object('pic0scaling', self.master).config(state='disabled')
        self.builder.get_object('pic0xoffset', self.master).config(state='disabled')
        self.builder.get_object('pic0yoffset', self.master).config(state='disabled')
        self.builder.get_variable('title_variable').set('')
        self.builder.get_variable('snd0_variable').set('')
        self.builder.get_object('snd0', self.master).config(filetypes=[('Audio files', ['.wav']), ('All Files', ['*.*', '*'])])
        self.builder.get_variable('logo_variable').set('')
        self.builder.get_object('logo', self.master).config(filetypes=[('Audio files', ['.png', '.PNG']), ('All Files', ['*.*', '*'])])

        self.builder.get_object('manual', self.master).config(state='disabled')
        self.builder.get_object('manual', self.master).config(filetypes=[('All Files', ['*.*', '*'])])
        self.builder.get_variable('manual_variable').set('')
        self.builder.get_variable('pic0scaling_variable').set('')
        self.builder.get_variable('pic0xoffset_variable').set('')
        self.builder.get_variable('pic0yoffset_variable').set('')
        self.builder.get_variable('import_summary_variable').set('')
        self.builder.get_variable('plan_summary_variable').set('')
        self.conversion_plan = None

    def update_prefs(self):
        PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(PREFERENCES_PATH, "w") as f:
            f.write('%s:%s\n' % ('undither', self.builder.get_variable('psx_undither_variable').get()))
            f.write('%s:%s\n' % ('pic1aslogo', self.builder.get_variable('pic1aslogo_variable').get()))
            f.write('%s:%s\n' % ('nopstitleimg', self.builder.get_variable('nopstitleimg_variable').get()))
            f.write('%s:%s\n' % ('watermark', self.builder.get_variable('watermark_variable').get()))
            f.write('%s:%s\n' % ('cdda', self.builder.get_variable('cdda_variable').get()))
            f.write('%s:%s\n' % ('force_ntsc', self.builder.get_variable('force_ntsc_variable').get()))
            f.write('%s:%s\n' % ('pic0_disabled', self.builder.get_variable('pic0_disabled_variable').get()))
            f.write('%s:%s\n' % ('pic1_disabled', self.builder.get_variable('pic1_disabled_variable').get()))
            f.write('%s:%s\n' % ('snd0_disabled', self.builder.get_variable('snd0_disabled_variable').get()))
            f.write('%s:%s\n' % ('target', self.builder.get_variable('target_variable').get()))
            f.write('%s:%s\n' % ('dir', self.builder.get_variable('pkgdir_variable').get()))
            if self.path_dir:
                f.write('%s:%s\n' % ('path', self.path_dir))


    def read_prefs(self):
        with open(PREFERENCES_PATH, "r") as f:
            for x in f.read().splitlines():
                key, val = x.split(':', 1)
                if key == 'undither':
                    self.builder.get_variable('psx_undither_variable').set(val)
                if key == 'pic1aslogo':
                    self.builder.get_variable('pic1aslogo_variable').set(val)
                    self.pic1aslogo = val
                if key == 'nopstitleimg':
                    self.builder.get_variable('nopstitleimg_variable').set(val)
                    self.nopstitleimg = val
                if key == 'watermark':
                    self.builder.get_variable('watermark_variable').set(val)
                    self.watermark = val
                if key == 'cdda':
                    self.builder.get_variable('cdda_variable').set(val)
                    self.cdda = val
                if key == 'force_ntsc':
                    self.builder.get_variable('force_ntsc_variable').set(val)
                if key == 'pic0_disabled':
                    self.builder.get_variable('pic0_disabled_variable').set(val)
                    self.disable_pic0 = val
                if key == 'pic1_disabled':
                    self.builder.get_variable('pic1_disabled_variable').set(val)
                    self.disable_pic1 = val
                if key == 'snd0_disabled':
                    self.builder.get_variable('snd0_disabled_variable').set(val)
                    self.disable_snd0 = val
                if key == 'target' and val in TARGET_VALUES:
                    self.builder.get_variable('target_variable').set(val)
                if key == 'dir':
                    self.builder.get_variable('pkgdir_variable').set(val)
                    self.pkgdir = val
                if key == 'path':
                    self.path_dir = val
                    if self.path_dir:
                        self.builder.get_object('disc1', self.master).config(initialdir=self.path_dir)
                        self.builder.get_object('disc2', self.master).config(initialdir=self.path_dir)
                        self.builder.get_object('disc3', self.master).config(initialdir=self.path_dir)
                        self.builder.get_object('disc4', self.master).config(initialdir=self.path_dir)
                        self.builder.get_object('disc5', self.master).config(initialdir=self.path_dir)


    def on_theme_selected(self, event):
        self.master.config(cursor='watch')
        self._theme = self.builder.get_object('theme', self.master).get()
        self.update_assets()
        self.master.config(cursor='')

    def fetch_pic0(self, game=None):
        disc_id = self.disc_ids[0]

        self.pic0 = None
        if self.pic0_path:
            self.pic0 = Image.open(self.pic0_path)
            self.pic0_orig = Image.open(self.pic0_path)
        if not self.pic0 and self._theme != '':
            self.pic0_orig = popfe.get_image_from_theme(self._theme, disc_id, self.subdir, 'PIC0.PNG')
            if not self.pic0:
                self.pic0_orig = popfe.get_image_from_theme(self._theme, disc_id, self.subdir, 'PIC0.png')
            self.pic0 = self.pic0_orig
        if not self.pic0:
            if game is None and disc_id in games:
                game = popfe.get_game_from_gamelist(disc_id)
            self.pic0_orig = popfe.get_pic0_from_game(disc_id, game, self.cue_file_orig, no_scaling=True)
            self.pic0 = popfe.rescale_pic0(
                self.pic0_orig,
                self.pic0scaling,
                (self.pic0xoffset, self.pic0yoffset),
            )
        if self.pic0:
            temp_files.append(self.subdir + 'PIC0.PNG')
            self.pic0.resize((128,80), Image.Resampling.HAMMING).save(self.subdir + 'PIC0.PNG')
            self.pic0_tk = tk.PhotoImage(file = self.subdir + 'PIC0.PNG')
            c = self.builder.get_object('pic0_canvas', self.master)
            c.create_image(0, 0, image=self.pic0_tk, anchor='nw')
        
    def update_assets(self, update_icon0=True, update_pic0=True, update_pic1=True):
        if not self.disc_ids:
            return
        if not self.cue_file_orig:
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
            print('Fetching ICON0') if verbose else None
            self.icon0 = None
            if self.icon0_path:
                self.icon0 = Image.open(self.icon0_path)
            elif self._theme != '':
                print('Get icon0 from theme')
                self.icon0 = popfe.get_image_from_theme(self._theme, disc_id, self.subdir, 'ICON0.PNG')
                if not self.icon0:
                    self.icon0 = popfe.get_image_from_theme(self._theme, disc_id, self.subdir, 'ICON0.png')
                if self.icon0:
                    self.icon0 = self.icon0.crop(self.icon0.getbbox())
            if not self.icon0:
                if disc_id in games:
                    self.icon0 = popfe.get_icon0_from_game(disc_id, game, self.cue_file_orig, self.subdir + 'ICON0.PNG', psp_ntsc_u_frame=self.builder.get_variable('ntsc_u_icon0_variable').get() == 'on', psn_frame_size=((80,80),(62,62)))
                else:
                    self.icon0 = Image.new('RGBA', (80, 80), (255, 255, 255, 0))
            if self.icon0:
                temp_files.append(self.subdir + 'ICON0.PNG')
                self.icon0.resize((80,80), Image.Resampling.HAMMING).save(self.subdir + 'ICON0.PNG')
                self.icon0_tk = tk.PhotoImage(file = self.subdir + 'ICON0.PNG')
                c = self.builder.get_object('icon0_canvas', self.master)
                c.create_image(0, 0, image=self.icon0_tk, anchor='nw')
 
        if self.snd0_disabled == 'off':
            snd0 = None
            print('Fetching SND0') if verbose else None
            if self.snd0_path:
                snd0 = self.snd0_path
            elif self._theme != '':
                snd0 = popfe.get_snd0_from_theme(self._theme, disc_id, self.subdir)
                if snd0:
                    temp_files.append(snd0)
            if not snd0 and disc_id in games and 'snd0' in games[disc_id]:
                snd0 = games[disc_id]['snd0']
            if snd0:
                self.builder.get_variable('snd0_variable').set(snd0)
                
        if update_pic0:
            print('Fetching PIC0') if verbose else None
            self.fetch_pic0(game=game)
        
        if update_pic1:
            print('Fetching PIC1') if verbose else None
            self.pic1 = None
            if self.pic1_path:
                self.pic1 = Image.open(self.pic1_path)
            if not self.pic1 and self._theme != '':
                self.pic1 = popfe.get_image_from_theme(self._theme, disc_id, self.subdir, 'PIC1.PNG')
                if not self.pic1:
                    self.pic1 = popfe.get_image_from_theme(self._theme, disc_id, self.subdir, 'PIC1.png')
            if not self.pic1:
                self.pic1 = popfe.get_pic1_from_game(disc_id, game, self.cue_file_orig)
            if self.pic1:
                temp_files.append(self.subdir + 'PIC1.PNG')
                self.pic1.resize((128,80), Image.Resampling.HAMMING).save(self.subdir + 'PIC1.PNG')
                self.pic1_tk = tk.PhotoImage(file = self.subdir + 'PIC1.PNG')
                c = self.builder.get_object('pic1_canvas', self.master)
                c.create_image(0, 0, image=self.pic1_tk, anchor='nw')

        self.update_preview()
        
    def _sync_disc_rows(self):
        loaded = len(self.cue_files)
        for idx in range(1, 6):
            chooser = self.builder.get_object('disc%d' % idx, self.master)
            disc_id = self.builder.get_object('discid%d' % idx, self.master)
            if idx <= loaded:
                chooser.grid()
                disc_id.grid()
                chooser.config(state='disabled')
                disc_id.config(state='normal')
            else:
                chooser.grid_remove()
                disc_id.grid_remove()
        self.builder.get_object('add_disc_button', self.master).config(
            state='disabled' if loaded >= 5 else 'normal'
        )

    def _target(self):
        selected = self.builder.get_variable('target_variable').get()
        return TARGET_VALUES.get(selected, 'psp')

    def _refresh_conversion_plan(self):
        if not self.cue_files:
            self.conversion_plan = None
            self.builder.get_variable('plan_summary_variable').set('')
            return None

        plan = build_psp_plan(
            self.cue_files,
            self._target(),
            fallback_disc_ids=self.real_disc_ids,
            analysis_cache=self.analysis_cache,
        )
        self.conversion_plan = plan
        for idx, disc_id in enumerate(plan.output_disc_ids, start=1):
            self.builder.get_variable('discid%d_variable' % idx).set(disc_id)

        self.cdda = 'on' if plan.use_cdda else 'off'
        self.builder.get_variable('cdda_variable').set(self.cdda)
        self.builder.get_variable('force_ntsc_variable').set(
            'on' if plan.force_ntsc else 'off'
        )
        self.builder.get_variable('psx_undither_variable').set(
            'on' if plan.undither else 'off'
        )

        profiles = tuple(
            dict.fromkeys(
                disc.conversion.rule_id or 'lossless default'
                for disc in plan.discs
            )
        )
        corrections = sum(
            action.kind not in {'preserve_disc', 'set_compression'}
            for disc in plan.discs
            for action in disc.conversion.actions
        )
        target = 'PSP' if plan.target == 'psp' else 'PS Vita / Adrenaline'
        summary = '%s  |  %d disc%s  |  %s  |  %d correction%s' % (
            target,
            len(plan.discs),
            '' if len(plan.discs) == 1 else 's',
            ', '.join(profiles),
            corrections,
            '' if corrections == 1 else 's',
        )
        if plan.warnings:
            summary += '  |  %d warning%s' % (
                len(plan.warnings),
                '' if len(plan.warnings) == 1 else 's',
            )
        self.builder.get_variable('plan_summary_variable').set(summary)
        return plan

    def on_target_selected(self, event=None):
        self.update_prefs()
        if not self.cue_files:
            return
        self.master.config(cursor='watch')
        self.master.update()
        try:
            self._refresh_conversion_plan()
        except Exception as error:
            messagebox.showerror(
                'Could not plan conversion', str(error), parent=self.master
            )
        finally:
            self.master.config(cursor='')

    def on_toggle_advanced(self):
        frame = self.builder.get_object('frame4', self.master)
        button = self.builder.get_object('advanced_button', self.master)
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            frame.grid()
            button.configure(text='Hide advanced overrides')
        else:
            frame.grid_remove()
            button.configure(text='Advanced overrides...')

    def load_disc(self, source_path, idx, fallback_title=None, refresh_plan=True):
        if idx != len(self.cue_files) + 1 or idx > 5:
            raise ValueError('Discs must be loaded in order, up to five.')

        source_path = os.path.abspath(source_path)
        self.path_dir = os.path.dirname(source_path)
        self.builder.get_variable('disc%d_variable' % idx).set(source_path)
        self.cue_file_orig = source_path
        print('Processing', source_path) if verbose else None

        cue_file, real_cue_file, img_file = popfe.process_disk_file(
            source_path, idx, temp_files, subdir=self.subdir
        )
        self.cue_file_orig = real_cue_file

        print('Scanning for Game ID') if verbose else None
        tmp = self.subdir + 'TMP%02d.iso' % idx
        disc_id, md5 = popfe.get_disc_id(
            cue_file, self.cue_file_orig, tmp, is_psp=True
        )
        print('ID', disc_id)
        temp_files.append(tmp)
        self.builder.get_variable('discid%d_variable' % idx).set(disc_id)

        self.img_files.append(img_file)
        self.disc_ids.append(disc_id)
        self.md5_sums.append(md5)
        self.real_disc_ids.append(disc_id)
        self.cue_files.append(cue_file)
        self.real_cue_files.append(real_cue_file)

        if not self.manual and disc_id in games and 'manual' in games[disc_id]:
            print('Found a manual for', disc_id) if verbose else None
            self.manual = games[disc_id]['manual']
        if disc_id in games and 'psp-use-cdda' in games[disc_id]:
            self.cdda = 'on'
            self.builder.get_variable('cdda_variable').set(self.cdda)

        if idx == 1:
            title = popfe.get_title_from_game(disc_id)
            if title == 'Unknown' and fallback_title:
                title = fallback_title
            self.builder.get_variable('title_variable').set(title)

            if disc_id in games and 'pic0-scaling' in games[disc_id]:
                self.pic0scaling = games[disc_id]['pic0-scaling']
            else:
                self.pic0scaling = 0.9
            self.builder.get_variable('pic0scaling_variable').set(self.pic0scaling)
            self.builder.get_object('pic0scaling', self.master).config(state='normal')

            if disc_id in games and 'pic0-offset' in games[disc_id]:
                self.pic0xoffset, self.pic0yoffset = games[disc_id]['pic0-offset']
            else:
                self.pic0xoffset = 0.1
                self.pic0yoffset = 0.1
            self.builder.get_variable('pic0xoffset_variable').set(self.pic0xoffset)
            self.builder.get_variable('pic0yoffset_variable').set(self.pic0yoffset)
            self.builder.get_object('pic0xoffset', self.master).config(state='normal')
            self.builder.get_object('pic0yoffset', self.master).config(state='normal')
            self.builder.get_variable('manual_variable').set(self.manual or '')
            self.builder.get_object('manual', self.master).config(state='normal')
            self.update_assets()
            self.builder.get_object('youtube_button', self.master).config(state='normal')
            self.builder.get_object('create_button', self.master).config(state='normal')

        self._sync_disc_rows()
        if refresh_plan:
            self._refresh_conversion_plan()
        self.update_prefs()
        print('Finished processing disc') if verbose else None

    def _load_disc_with_dialog(self, source_path, idx, fallback_title=None):
        self.master.config(cursor='watch')
        self.master.update()
        try:
            self.load_disc(source_path, idx, fallback_title=fallback_title)
        except Exception as error:
            messagebox.showerror('Could not load disc', str(error), parent=self.master)
            return False
        finally:
            self.master.config(cursor='')
        return True

    def on_add_disc(self):
        idx = len(self.cue_files) + 1
        if idx > 5:
            return
        source_path = filedialog.askopenfilename(
            title='Select PlayStation disc image',
            initialdir=self.path_dir or str(popfe_runtime.home),
            filetypes=DISC_FILETYPES,
        )
        if source_path:
            self._load_disc_with_dialog(source_path, idx)

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
        parts.extend(result.warnings)
        self.builder.get_variable('import_summary_variable').set('  |  '.join(parts))

    def import_folder(self, directory, import_all_discs=True):
        result = scan_psp_folder(
            directory,
            import_all_discs=import_all_discs,
        )
        self.init_data()
        self.path_dir = str(result.directory)
        self._apply_folder_assets(result.assets)
        for idx, source_path in enumerate(result.discs, start=1):
            self.load_disc(
                str(source_path),
                idx,
                fallback_title=result.fallback_title if idx == 1 else None,
                refresh_plan=False,
            )
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
        idx = int(event.widget.cget('title')[1])
        self._load_disc_with_dialog(source_path, idx)


    def update_preview(self):
        def has_transparency(img):
            if img.info.get("transparency", None) is not None:
                return True
            if img.mode == "P":
                transparent = img.info.get("transparency", -1)
                for _, index in img.getcolors():
                    if index == transparent:
                        return True
            elif img.mode == "RGBA":
                extrema = img.getextrema()
                if extrema[3][0] < 255:
                    return True

                return False

        if not len(self.disc_ids):
            return

        if self.pic0_disabled == 'on':
            _pic0 = None
        else:
            _pic0 = popfe.rescale_pic0(
                self.pic0_orig,
                self.pic0scaling,
                (self.pic0xoffset, self.pic0yoffset),
            )
        if self.pic1_disabled == 'on':
            _pic1 = Image.new('RGBA', (1920, 1080), (0,0,0))
            _pic1.putalpha(0)
        else:
            _pic1 = self.pic1

        if _pic0 and self.pic0.mode == 'P':
            _pic0 = _pic0.convert(mode='RGBA')
        c = self.builder.get_object('preview_canvas', self.master)
        if _pic1:
            p1 = _pic1.resize((382,216), Image.Resampling.HAMMING)
        else:
            p1 = Image.new('RGBA', (382,216), (0,0,0))
        p1 = p1.convert('RGBA')
        if _pic0:
            p0 = _pic0.resize((int(p1.size[0] * 0.55) , int(p1.size[1] * 0.58)), Image.Resampling.HAMMING)
            if has_transparency(p0):
                Image.Image.paste(p1, p0, box=(148,79), mask=p0)
            else:
                Image.Image.paste(p1, p0, box=(148,79))
        if self.icon0:
            i0 = self.icon0.resize((int(p1.size[1] * 0.25) , int(p1.size[1] * 0.25)), Image.Resampling.HAMMING)
            if has_transparency(i0):
                Image.Image.paste(p1, i0, box=(36,81), mask=i0)
            else:
                Image.Image.paste(p1, i0, box=(36,81))
        temp_files.append(self.subdir + 'PREVIEW.PNG')
        p1.save(self.subdir + 'PREVIEW.PNG')
        self.preview_tk = tk.PhotoImage(file = self.subdir + 'PREVIEW.PNG')
        c = self.builder.get_object('preview_canvas', self.master)
        c.create_image(0, 0, image=self.preview_tk, anchor='nw')
        

    def on_nopstitleimg(self):
        self.nopstitleimg = self.builder.get_variable('nopstitleimg_variable').get()
        self.update_prefs()
        
    def on_pic1aslogo(self):
        self.pic1aslogo = self.builder.get_variable('pic1aslogo_variable').get()
        self.update_prefs()
        
    def on_watermark(self):
        self.watermark = self.builder.get_variable('watermark_variable').get()
        self.update_prefs()
        
    def on_icon0_clicked(self, event):
        filetypes = [
            ('Image files', ['.png', '.PNG', '.jpg', '.JPG']),
            ('All Files', ['*.*', '*'])]
        path = tk.filedialog.askopenfilename(title='Select image for ICON0',filetypes=filetypes)
        try:
            os.stat(path)
            self.icon0 = Image.open(path)
        except:
            return
        self.icon0_path = path
        self.update_assets(update_pic0=False, update_pic1=False)
        self.update_preview()


    def on_pic0_disabled(self):
        self.pic0_disabled = self.builder.get_variable('pic0_disabled_variable').get()
        self.update_preview()
        self.update_prefs()

    def on_pic1_disabled(self):
        self.pic1_disabled = self.builder.get_variable('pic1_disabled_variable').get()
        self.update_preview()
        self.update_prefs()

    def on_snd0_disabled(self):
        self.snd0_disabled = self.builder.get_variable('snd0_disabled_variable').get()
        self.update_prefs()

    def on_pic0_clicked(self, event):
        filetypes = [
            ('Image files', ['.png', '.PNG', '.jpg', '.JPG']),
            ('All Files', ['*.*', '*'])]
        path = tk.filedialog.askopenfilename(title='Select image for PIC0',filetypes=filetypes)
        try:
            os.stat(path)
            self.pic0 = Image.open(path)
            self.pic0_orig = Image.open(path)
            self.pic0_path = path
        except:
            return

        temp_files.append(self.subdir + 'PIC0.PNG')
        self.pic0.resize((128,80), Image.Resampling.HAMMING).save(self.subdir + 'PIC0.PNG')
        self.pic0_tk = tk.PhotoImage(file = self.subdir + 'PIC0.PNG')
        c = self.builder.get_object('pic0_canvas', self.master)
        c.create_image(0, 0, image=self.pic0_tk, anchor='nw')
        self.update_preview()
        
    def on_pic1_clicked(self, event):
        filetypes = [
            ('Image files', ['.png', '.PNG', '.jpg', '.JPG']),
            ('All Files', ['*.*', '*'])]
        path = tk.filedialog.askopenfilename(title='Select image for PIC1',filetypes=filetypes)
        try:
            os.stat(path)
            self.pic1 = Image.open(path)
            self.pic1_path = path
        except:
            return
        temp_files.append(self.subdir + 'PIC1.PNG')
        self.pic1.resize((128,80), Image.Resampling.HAMMING).save(self.subdir + 'PIC1.PNG')
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
            if self.disc_ids[0] in games:
                games[self.disc_ids[0]]['pic0-scaling'] = self.pic0scaling
            self.update_preview()

    def on_pic0_xoffset(self, event):
        try:
            v = float(self.builder.get_variable('pic0xoffset_variable').get())
        except:
            return

        if v >= 0.0 and v != self.pic0xoffset and self.disc_ids:
            self.pic0xoffset = v
            if self.disc_ids[0] in games:
                games[self.disc_ids[0]]['pic0-offset'] = (self.pic0xoffset, self.pic0yoffset)
            self.update_preview()
            
    def on_pic0_yoffset(self, event):
        try:
            v = float(self.builder.get_variable('pic0yoffset_variable').get())
        except:
            return

        if v >= 0.0 and v != self.pic0yoffset and self.disc_ids:
            self.pic0yoffset = v
            if self.disc_ids[0] in games:
                games[self.disc_ids[0]]['pic0-offset'] = (self.pic0xoffset, self.pic0yoffset)
            self.update_preview()
            
    def on_dir_changed(self, event):
        self.pkgdir = event.widget.cget('path')
        self.update_prefs()

    def on_youtube_audio(self):
        if not have_pytube:
            return
        self.master.config(cursor='watch')
        a = pytube.contrib.search.Search(self.builder.get_variable('title_variable').get() + ' ps1 ost')
        if a:
            self.builder.get_variable('snd0_variable').set('https://www.youtube.com/watch?v=' + a.results[0].video_id)
           
        self.master.config(cursor='')

    def on_create_eboot(self):
        if not self.cue_files:
            return

        self.master.config(cursor='watch')
        self.master.update()
        try:
            plan = self.conversion_plan or self._refresh_conversion_plan()
            pkgdir = self.builder.get_variable('pkgdir_variable').get()
            title = self.builder.get_variable('title_variable').get()
            disc_ids = tuple(
                self.builder.get_variable('discid%d_variable' % (idx + 1)).get()
                for idx in range(len(self.cue_files))
            )
            print('Creating EBOOT')
            print('DISC', disc_ids[0])
            print('TITLE', title)

            subchannels = tuple(
                popfe.generate_subchannels(disc.libcrypt_magic_word)
                if disc.libcrypt_magic_word is not None
                else None
                for disc in plan.discs
            )

            snd0 = self.builder.get_variable('snd0_variable').get()
            if snd0[:24] == 'https://www.youtube.com/':
                snd0 = popfe.get_snd0_from_link(snd0, subdir=self.subdir)
                if snd0:
                    temp_files.append(snd0)

            manual = self.builder.get_variable('manual_variable').get()
            if manual and manual != 'None':
                manual = popfe.create_manual(
                    manual, self.disc_ids[0], subdir=self.subdir
                )
            else:
                manual = None

            if pkgdir:
                ebootdir = pkgdir
            elif popfe_runtime.is_macos:
                ebootdir = str(popfe_runtime.home)
            else:
                ebootdir = '.'

            verify_planned_patch_sources(plan, self.img_files)
            working_cues, working_images = popfe.apply_planned_patches(
                self.cue_files,
                self.img_files,
                tuple(disc.patches for disc in plan.discs),
                self.subdir,
            )

            undither = (
                self.builder.get_variable('psx_undither_variable').get() == 'on'
            )
            ntsc = self.builder.get_variable('force_ntsc_variable').get() == 'on'
            cdda = self.builder.get_variable('cdda_variable').get() == 'on'
            if undither:
                working_cues, working_images = popfe.patch_undither(
                    self.real_disc_ids,
                    working_cues,
                    working_images,
                    subdir=self.subdir,
                )

            aea_files, _ = popfe.generate_aea_files(
                working_cues, working_images, self.subdir
            )
            planned_configs = read_planned_configs(
                plan, force_ntsc=False, cdda=False
            )
            expected_configs = read_planned_configs(
                plan, force_ntsc=ntsc, cdda=cdda
            )
            expected_sizes = execution_decoded_sizes(
                plan, use_cdda=cdda
            )
            expected_hashes = expected_decoded_hashes(
                plan, working_images, use_cdda=cdda
            )
            expected_tocs = tuple(
                bytes(popfe.get_toc_from_cue(cue)).ljust(1020, b'\x00')
                for cue in working_cues
            )

            logo = None
            logo_path = self.builder.get_variable('logo_variable').get()
            if logo_path:
                logo = Image.open(logo_path)

            output_path = popfe.create_psp(
                ebootdir,
                disc_ids,
                self.real_disc_ids,
                title,
                self.icon0,
                self.pic0 if self.pic0_disabled == 'off' else None,
                self.pic1 if self.pic1_disabled == 'off' else None,
                working_cues,
                self.real_cue_files,
                working_images,
                [],
                aea_files,
                subdir=self.subdir,
                snd0=snd0,
                no_pstitleimg=self.nopstitleimg == 'on',
                watermark=self.watermark == 'on',
                subchannels=subchannels,
                manual=manual,
                use_cdda=cdda,
                logo=self.pic1 if self.pic1aslogo == 'on' else logo,
                no_libcrypt=True,
                psx_undither=False,
                force_ntsc=ntsc,
                cdda=cdda,
                planned_configs=planned_configs,
                compression_level=plan.compression_level,
            )

            output_path = Path(output_path)
            report_path = output_path.with_name('PSXFoundry-report.txt')
            validation = validate_generated_eboot(
                output_path,
                EbootExpectation(
                    disc_ids=disc_ids,
                    decoded_sizes=expected_sizes,
                    decoded_sha256=expected_hashes,
                    tocs=expected_tocs,
                    configs=expected_configs,
                    subchannel_records=tuple(
                        len(data) // 12 if data is not None else 0
                        for data in subchannels
                    ),
                ),
                report_path=report_path,
            )
            report = render_psp_workflow_report(plan)
            override_lines = []
            if disc_ids != plan.output_disc_ids:
                override_lines.append('- Disc IDs: ' + ', '.join(disc_ids))
            if cdda != plan.use_cdda:
                override_lines.append(
                    f'- CD audio: {"raw" if cdda else "ATRAC3"}'
                )
            if ntsc != plan.force_ntsc:
                override_lines.append(
                    f'- Force NTSC: {"yes" if ntsc else "no"}'
                )
            if undither != plan.undither:
                override_lines.append(
                    f'- Undither: {"yes" if undither else "no"}'
                )
            if self.nopstitleimg == 'on':
                override_lines.append('- PSTITLEIMG: disabled')
            overrides = 'Overrides:\n' + '\n'.join(
                override_lines or ['- None']
            ) + '\n'
            report_path.write_text(
                report + overrides + validation.to_text(),
                encoding='utf-8',
            )
            if not validation.ok:
                raise RuntimeError(
                    'EBOOT validation failed. See ' + str(report_path)
                )
        except Exception as error:
            messagebox.showerror(
                'Could not create EBOOT', str(error), parent=self.master
            )
            return
        finally:
            self.master.config(cursor='')

        d = FinishedDialog(self.master)
        self.master.wait_window(d)
        self.init_data()

    def on_reset(self):
        self.init_data()

    def on_cdda(self):
        self.cdda = self.builder.get_variable('cdda_variable').get()
        self.update_prefs()

    def on_force_ntsc(self):
        self.update_prefs()

    def on_psx_undither(self):
        self.update_prefs()

    def on_ntsc_u_icon0(self):
        self.update_assets(update_pic0=False, update_pic1=False)
        self.update_prefs()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', action='store_true', help='Verbose')
    args = parser.parse_args()

    if args.v:
        verbose = True

    smoke_test = os.environ.get("POPFE_GUI_SMOKE_TEST") == "1"
    root = tk.Tk()
    if smoke_test:
        root.withdraw()
    if popfe_runtime.is_macos:
        install_tk_error_handler(root, popfe_runtime, "psp", "Pop-FE PSP Error")
    app = PopFePs3App(root)
    root.title('Pop-FE PSP')
    root.minsize(820, 560)
    root.rowconfigure(0, weight=1)
    root.columnconfigure(0, weight=1)
    app.mainwindow.columnconfigure(0, weight=1)
    app.mainwindow.columnconfigure(1, weight=1)
    if smoke_test:
        import_directory = os.environ.get('POPFE_GUI_IMPORT_FOLDER')
        if import_directory:
            result = app.import_folder(
                import_directory,
                import_all_discs=(
                    os.environ.get('POPFE_GUI_IMPORT_ALL_DISCS', '1') != '0'
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
    
