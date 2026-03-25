"""
SimMovieMaker v2.0 - Main GUI application.

Refactored from the original SimMovieMaker.py.  Supports both image-based
movie creation (the original workflow) and direct video file operations
powered by ffmpeg.
"""

import os
import sys
import cv2
import numpy as np
import tkinter as tk
from tkinter import filedialog, ttk, messagebox, simpledialog
from PIL import Image, ImageTk
import json
import threading
from datetime import datetime

from .ffmpeg_utils import check_ffmpeg, get_ffmpeg_help_text, FFmpegNotFoundError
from . import video_ops
from .dialogs import (
    ProgressDialog, VideoInfoDialog, MetadataDialog, SplitVideoDialog,
    TrimDialog, SpeedDialog, ExtractFramesDialog, FFmpegHelpDialog,
    MergeOptionsDialog, format_duration,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")
_VIDEO_EXTENSIONS = (
    ".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm", ".m4v",
    ".mpg", ".mpeg", ".ts",
)

_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Icon helpers
# ---------------------------------------------------------------------------

def _find_icon_path():
    """Search for smm.ico in known locations and return the first hit."""
    candidates = [
        os.path.join(_PACKAGE_DIR, "assets", "smm.ico"),
        os.path.join(_PACKAGE_DIR, "smm.ico"),
        os.path.join(os.path.dirname(_PACKAGE_DIR), "assets", "smm.ico"),
        os.path.join(os.path.dirname(_PACKAGE_DIR), "smm.ico"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _install_icon_hook(root, icon_path):
    """Monkey-patch ``tk.Toplevel`` so every new Toplevel window automatically
    gets the application icon."""
    if icon_path is None:
        return

    _OriginalToplevel = tk.Toplevel

    class _IconifiedToplevel(_OriginalToplevel):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

    tk.Toplevel = _IconifiedToplevel


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _is_video_file(path):
    return os.path.splitext(path)[1].lower() in _VIDEO_EXTENSIONS


def _is_image_file(path):
    return os.path.splitext(path)[1].lower() in _IMAGE_EXTENSIONS


def _listbox_display(media_entry):
    """Return the display string for a media_files entry."""
    basename = os.path.basename(media_entry["path"])
    if media_entry["type"] == "video":
        return f"[V] {basename}"
    return basename


# ---------------------------------------------------------------------------
# Main application class
# ---------------------------------------------------------------------------

class SimMovieMaker:
    """Main GUI application for SimMovieMaker v2.0."""

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(self, root):
        self.root = root
        self.root.title("SimMovieMaker v2.0")
        self.root.geometry("1200x800")

        # Icon -------------------------------------------------------
        self.icon_path = _find_icon_path()
        if self.icon_path:
            try:
                self.root.iconbitmap(self.icon_path)
            except tk.TclError:
                pass
        _install_icon_hook(self.root, self.icon_path)

        # Project data -----------------------------------------------
        self.project_file = None
        # Unified media list: list of dicts {'path': str, 'type': 'image'|'video'}
        self.media_files = []
        self.selected_indices = []
        self.current_preview_index = 0
        self.current_photo = None  # prevent GC of PhotoImage

        self.output_settings = {
            "format": "mp4",
            "fps": 30,
            "codec": "H264",
            "quality": 80,
        }

        # FFmpeg status (checked asynchronously) ----------------------
        self.ffmpeg_status = None

        # Build UI ----------------------------------------------------
        self.create_menu_bar()
        self.create_layout()

        # Kick off ffmpeg check in background
        threading.Thread(target=self._check_ffmpeg_async, daemon=True).start()

    # ------------------------------------------------------------------
    # Backward-compat helpers for the old image_files list
    # ------------------------------------------------------------------

    @property
    def image_files(self):
        """Return a flat list of paths (images only) for backward compat."""
        return [m["path"] for m in self.media_files if m["type"] == "image"]

    # ------------------------------------------------------------------
    # FFmpeg background check
    # ------------------------------------------------------------------

    def _check_ffmpeg_async(self):
        self.ffmpeg_status = check_ffmpeg()
        if self.ffmpeg_status["available"]:
            msg = f"Ready  |  FFmpeg: {self.ffmpeg_status['version']}"
        else:
            msg = "Ready  |  WARNING: FFmpeg not found -- video operations unavailable"
        self.root.after(0, self.status_var.set, msg)

    def _require_ffmpeg(self):
        """Show a warning and return False if ffmpeg is not available."""
        if self.ffmpeg_status and self.ffmpeg_status["available"]:
            return True
        messagebox.showwarning(
            "FFmpeg Required",
            "This operation requires FFmpeg, which was not found on your system.\n\n"
            "Use Help > FFmpeg Status for installation instructions.",
        )
        return False

    # ------------------------------------------------------------------
    # Menu bar
    # ------------------------------------------------------------------

    def create_menu_bar(self):
        menubar = tk.Menu(self.root)

        # -- File menu -------------------------------------------------
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Project", command=self.new_project)
        file_menu.add_command(label="Open Project", command=self.open_project)
        file_menu.add_command(label="Save Project", command=self.save_project)
        file_menu.add_command(label="Save Project As", command=self.save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Import Images", command=self.import_images)
        file_menu.add_command(label="Import Sequence", command=self.import_sequence)
        file_menu.add_command(label="Import Video Files", command=self.import_videos)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        # -- Edit menu -------------------------------------------------
        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Select All", command=self.select_all)
        edit_menu.add_command(label="Deselect All", command=self.deselect_all)
        edit_menu.add_separator()
        edit_menu.add_command(label="Delete Selected", command=self.delete_selected)
        edit_menu.add_separator()
        edit_menu.add_command(label="Move Up", command=lambda: self.move_selected(-1))
        edit_menu.add_command(label="Move Down", command=lambda: self.move_selected(1))
        menubar.add_cascade(label="Edit", menu=edit_menu)

        # -- Preview menu ----------------------------------------------
        preview_menu = tk.Menu(menubar, tearoff=0)
        preview_menu.add_command(label="Preview Current Frame", command=self.preview_current)
        preview_menu.add_command(label="Create Preview Video", command=self.create_preview)
        menubar.add_cascade(label="Preview", menu=preview_menu)

        # -- Video (image->video creation) menu ------------------------
        video_create_menu = tk.Menu(menubar, tearoff=0)
        video_create_menu.add_command(label="Output Settings", command=self.show_output_settings)
        video_create_menu.add_separator()
        video_create_menu.add_command(label="Create Video", command=self.create_video)
        menubar.add_cascade(label="Video", menu=video_create_menu)

        # -- Video Operations menu (ffmpeg) ----------------------------
        vidops_menu = tk.Menu(menubar, tearoff=0)
        vidops_menu.add_command(label="Merge Videos", command=self.merge_videos)
        vidops_menu.add_command(label="Split Video", command=self.split_video)
        vidops_menu.add_command(label="Trim Video", command=self.trim_video)
        vidops_menu.add_separator()
        vidops_menu.add_command(label="Mute Audio", command=self.mute_audio)
        vidops_menu.add_command(label="Extract Audio", command=self.extract_audio)
        vidops_menu.add_command(label="Add Audio", command=self.add_audio)
        vidops_menu.add_separator()
        vidops_menu.add_command(label="Change Speed", command=self.change_speed)
        vidops_menu.add_command(label="Extract Frames", command=self.extract_frames)
        vidops_menu.add_command(label="Convert Format", command=self.convert_format)
        vidops_menu.add_command(label="Create GIF", command=self.create_gif)
        menubar.add_cascade(label="Video Ops", menu=vidops_menu)

        # -- Filters menu ----------------------------------------------
        filter_menu = tk.Menu(menubar, tearoff=0)

        size_menu = tk.Menu(filter_menu, tearoff=0)
        size_menu.add_command(label="Crop", command=lambda: self.apply_filter("crop"))
        size_menu.add_command(label="Resize", command=lambda: self.apply_filter("resize"))
        size_menu.add_command(label="Rotate", command=lambda: self.apply_filter("rotate"))
        filter_menu.add_cascade(label="Adjust Size", menu=size_menu)

        color_menu = tk.Menu(filter_menu, tearoff=0)
        color_menu.add_command(label="Brightness", command=lambda: self.apply_filter("brightness"))
        color_menu.add_command(label="Contrast", command=lambda: self.apply_filter("contrast"))
        color_menu.add_command(label="Grayscale", command=lambda: self.apply_filter("grayscale"))
        filter_menu.add_cascade(label="Adjust Colors", menu=color_menu)

        overlay_menu = tk.Menu(filter_menu, tearoff=0)
        overlay_menu.add_command(label="Text Overlay", command=lambda: self.apply_filter("text_overlay"))
        overlay_menu.add_command(label="Scale Bar", command=lambda: self.apply_filter("scale_bar"))
        overlay_menu.add_command(label="Timestamp", command=lambda: self.apply_filter("timestamp"))
        filter_menu.add_cascade(label="Overlay", menu=overlay_menu)

        menubar.add_cascade(label="Filters", menu=filter_menu)

        # -- Metadata menu ---------------------------------------------
        meta_menu = tk.Menu(menubar, tearoff=0)
        meta_menu.add_command(label="View Metadata", command=self.view_metadata)
        meta_menu.add_command(label="Edit Metadata", command=self.edit_metadata)
        meta_menu.add_command(label="Strip Metadata", command=self.strip_metadata)
        menubar.add_cascade(label="Metadata", menu=meta_menu)

        # -- Tools menu ------------------------------------------------
        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="Batch Process", command=self.batch_process)
        tools_menu.add_command(label="Export File List", command=self.export_file_list)
        tools_menu.add_command(label="Import File List", command=self.import_file_list)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        # -- Help menu -------------------------------------------------
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Documentation", command=self.show_documentation)
        help_menu.add_separator()
        help_menu.add_command(label="FFmpeg Status", command=self.show_ffmpeg_status)
        help_menu.add_command(label="Check for FFmpeg", command=self.check_for_ffmpeg)
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def create_layout(self):
        # Main frame
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Split into left and right panels
        panel = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        panel.pack(fill=tk.BOTH, expand=True)

        # -- Left panel: file list ------------------------------------
        left_frame = ttk.Frame(panel, width=400)
        panel.add(left_frame)

        ttk.Label(left_frame, text="Media Files").pack(anchor=tk.W, pady=(0, 5))

        list_frame = ttk.Frame(left_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.file_listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED)
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.file_listbox.bind("<<ListboxSelect>>", self.on_file_select)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.file_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_listbox.config(yscrollcommand=scrollbar.set)

        # Buttons under list
        button_frame = ttk.Frame(left_frame)
        button_frame.pack(fill=tk.X, pady=5)

        ttk.Button(button_frame, text="Add Files", command=self.import_images).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="Add Videos", command=self.import_videos).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="Remove", command=self.delete_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="Up", width=3, command=lambda: self.move_selected(-1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="Down", width=3, command=lambda: self.move_selected(1)).pack(side=tk.LEFT, padx=2)

        # -- Right panel: preview and properties ----------------------
        right_frame = ttk.Frame(panel)
        panel.add(right_frame)

        ttk.Label(right_frame, text="Preview").pack(anchor=tk.W, pady=(0, 5))

        self.preview_frame = ttk.Frame(right_frame, relief=tk.SUNKEN, borderwidth=1)
        self.preview_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.preview_canvas = tk.Canvas(self.preview_frame, bg="black")
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)

        # Preview navigation
        controls_frame = ttk.Frame(right_frame)
        controls_frame.pack(fill=tk.X, pady=5)

        ttk.Button(controls_frame, text="<<", width=3, command=self.preview_first).pack(side=tk.LEFT, padx=2)
        ttk.Button(controls_frame, text="<", width=3, command=self.preview_previous).pack(side=tk.LEFT, padx=2)

        self.preview_label = ttk.Label(controls_frame, text="0/0")
        self.preview_label.pack(side=tk.LEFT, padx=10)

        ttk.Button(controls_frame, text=">", width=3, command=self.preview_next).pack(side=tk.LEFT, padx=2)
        ttk.Button(controls_frame, text=">>", width=3, command=self.preview_last).pack(side=tk.LEFT, padx=2)
        ttk.Button(controls_frame, text="Preview Video", command=self.create_preview).pack(side=tk.RIGHT, padx=2)

        # Properties (output settings)
        properties_frame = ttk.LabelFrame(right_frame, text="Output Properties")
        properties_frame.pack(fill=tk.X, pady=10)

        # FPS
        fps_frame = ttk.Frame(properties_frame)
        fps_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(fps_frame, text="FPS:").pack(side=tk.LEFT)
        self.fps_var = tk.StringVar(value=str(self.output_settings["fps"]))
        fps_spinbox = ttk.Spinbox(fps_frame, from_=1, to=120, textvariable=self.fps_var, width=5)
        fps_spinbox.pack(side=tk.LEFT, padx=5)
        fps_spinbox.bind("<<SpinboxSelected>>", self.update_fps)

        # Format
        format_frame = ttk.Frame(properties_frame)
        format_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(format_frame, text="Format:").pack(side=tk.LEFT)
        self.format_var = tk.StringVar(value=self.output_settings["format"])
        format_combo = ttk.Combobox(format_frame, textvariable=self.format_var,
                                    values=["mp4", "avi", "mov", "webm"], width=5)
        format_combo.pack(side=tk.LEFT, padx=5)
        format_combo.bind("<<ComboboxSelected>>", self.update_format)

        # Codec
        codec_frame = ttk.Frame(properties_frame)
        codec_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(codec_frame, text="Codec:").pack(side=tk.LEFT)
        self.codec_var = tk.StringVar(value=self.output_settings["codec"])
        codec_combo = ttk.Combobox(codec_frame, textvariable=self.codec_var,
                                   values=["H264", "MJPG", "XVID", "VP9"], width=5)
        codec_combo.pack(side=tk.LEFT, padx=5)
        codec_combo.bind("<<ComboboxSelected>>", self.update_codec)

        # Video info label (shown when a video is selected)
        self.video_info_label = ttk.Label(right_frame, text="", wraplength=500,
                                          foreground="gray")
        self.video_info_label.pack(fill=tk.X, pady=(0, 5))

        # Create Video button
        ttk.Button(right_frame, text="Create Video", command=self.create_video).pack(anchor=tk.E, pady=10)

        # Status bar
        self.status_var = tk.StringVar(value="Starting up...")
        status_bar = ttk.Label(self.root, textvariable=self.status_var,
                               relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    # ------------------------------------------------------------------
    # Listbox helpers
    # ------------------------------------------------------------------

    def _refresh_listbox(self):
        """Rebuild the listbox from self.media_files."""
        self.file_listbox.delete(0, tk.END)
        for entry in self.media_files:
            self.file_listbox.insert(tk.END, _listbox_display(entry))

    def _get_selected_video_path(self):
        """Return the path of the first selected video file, or None."""
        indices = list(self.file_listbox.curselection())
        for idx in indices:
            if idx < len(self.media_files) and self.media_files[idx]["type"] == "video":
                return self.media_files[idx]["path"]
        return None

    def _get_selected_video_paths(self):
        """Return paths of all selected video files."""
        indices = list(self.file_listbox.curselection())
        paths = []
        for idx in indices:
            if idx < len(self.media_files) and self.media_files[idx]["type"] == "video":
                paths.append(self.media_files[idx]["path"])
        return paths

    # ------------------------------------------------------------------
    # File menu: project management
    # ------------------------------------------------------------------

    def new_project(self):
        self.project_file = None
        self.media_files = []
        self.selected_indices = []
        self.current_preview_index = 0
        self.file_listbox.delete(0, tk.END)
        self.update_preview()
        self.video_info_label.config(text="")
        self.status_var.set("New project created")

    def open_project(self):
        filename = filedialog.askopenfilename(
            title="Open Project",
            filetypes=[("SimMovieMaker Project", "*.smp"), ("All files", "*.*")],
        )
        if not filename:
            return

        try:
            with open(filename, "r") as f:
                project_data = json.load(f)

            self.project_file = filename

            # Handle both old format (list of strings) and new format (list of dicts)
            raw_files = project_data.get("media_files") or project_data.get("image_files", [])
            self.media_files = []
            for item in raw_files:
                if isinstance(item, str):
                    mtype = "video" if _is_video_file(item) else "image"
                    self.media_files.append({"path": item, "type": mtype})
                elif isinstance(item, dict):
                    self.media_files.append(item)

            self.output_settings = project_data.get("output_settings", self.output_settings)

            # Update UI
            self._refresh_listbox()
            self.fps_var.set(str(self.output_settings["fps"]))
            self.format_var.set(self.output_settings["format"])
            self.codec_var.set(self.output_settings["codec"])

            self.current_preview_index = 0
            self.update_preview()
            self.status_var.set(f"Project loaded: {os.path.basename(filename)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open project: {e}")

    def save_project(self):
        if not self.project_file:
            self.save_project_as()
            return
        self._save_project(self.project_file)

    def save_project_as(self):
        filename = filedialog.asksaveasfilename(
            title="Save Project As",
            defaultextension=".smp",
            filetypes=[("SimMovieMaker Project", "*.smp"), ("All files", "*.*")],
        )
        if not filename:
            return
        self.project_file = filename
        self._save_project(filename)

    def _save_project(self, filename):
        project_data = {
            "media_files": self.media_files,
            "output_settings": self.output_settings,
            "saved_at": datetime.now().isoformat(),
        }
        try:
            with open(filename, "w") as f:
                json.dump(project_data, f, indent=2)
            self.status_var.set(f"Project saved: {os.path.basename(filename)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save project: {e}")

    # ------------------------------------------------------------------
    # File menu: import images / sequences / videos
    # ------------------------------------------------------------------

    def import_images(self):
        filenames = filedialog.askopenfilenames(
            title="Select Image Files",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp"),
                ("All files", "*.*"),
            ],
        )
        if not filenames:
            return

        existing_paths = {m["path"] for m in self.media_files}
        added = 0
        for fn in filenames:
            if fn not in existing_paths:
                entry = {"path": fn, "type": "image"}
                self.media_files.append(entry)
                self.file_listbox.insert(tk.END, _listbox_display(entry))
                added += 1

        self.status_var.set(f"Added {added} image(s)")
        if self.media_files and self.current_preview_index == 0:
            self.update_preview()

    def import_sequence(self):
        directory = filedialog.askdirectory(title="Select Directory with Image Sequence")
        if not directory:
            return

        pattern = simpledialog.askstring(
            "Image Sequence",
            "Enter filename pattern (e.g. 'frame_*.png' or use * as wildcard):",
            initialvalue="*.png",
            parent=self.root,
        )
        if not pattern:
            return

        import re as _re
        regex_pattern = pattern.replace(".", r"\.").replace("*", ".*")

        files = sorted(os.listdir(directory))
        matching_files = [f for f in files if _re.match(regex_pattern, f)]

        if not matching_files:
            messagebox.showinfo(
                "No files found",
                f"No files matching pattern '{pattern}' found in the selected directory.",
            )
            return

        existing_paths = {m["path"] for m in self.media_files}
        added = 0
        for fn in matching_files:
            full_path = os.path.join(directory, fn)
            if full_path not in existing_paths:
                entry = {"path": full_path, "type": "image"}
                self.media_files.append(entry)
                self.file_listbox.insert(tk.END, _listbox_display(entry))
                added += 1

        self.status_var.set(f"Added {added} file(s) from sequence")
        if self.media_files and self.current_preview_index == 0:
            self.update_preview()

    def import_videos(self):
        filenames = filedialog.askopenfilenames(
            title="Select Video Files",
            filetypes=[
                ("Video files", "*.mp4 *.avi *.mov *.mkv *.wmv *.flv *.webm *.m4v"),
                ("All files", "*.*"),
            ],
        )
        if not filenames:
            return

        existing_paths = {m["path"] for m in self.media_files}
        added = 0
        for fn in filenames:
            if fn not in existing_paths:
                entry = {"path": fn, "type": "video"}
                self.media_files.append(entry)
                self.file_listbox.insert(tk.END, _listbox_display(entry))
                added += 1

        self.status_var.set(f"Added {added} video(s)")

    # ------------------------------------------------------------------
    # Edit menu
    # ------------------------------------------------------------------

    def select_all(self):
        self.file_listbox.selection_set(0, tk.END)
        self.update_selected_indices()

    def deselect_all(self):
        self.file_listbox.selection_clear(0, tk.END)
        self.selected_indices = []

    def delete_selected(self):
        if not self.selected_indices:
            return

        indices = sorted(self.selected_indices, reverse=True)
        for idx in indices:
            if idx < len(self.media_files):
                del self.media_files[idx]
            self.file_listbox.delete(idx)

        self.selected_indices = []

        if self.media_files:
            self.current_preview_index = min(self.current_preview_index,
                                             len(self.media_files) - 1)
            self.update_preview()
        else:
            self.current_preview_index = 0
            self.preview_canvas.delete("all")
            self.preview_label.config(text="0/0")

    def move_selected(self, direction):
        if not self.selected_indices or len(self.selected_indices) != 1:
            return

        idx = self.selected_indices[0]
        target_idx = idx + direction

        if target_idx < 0 or target_idx >= len(self.media_files):
            return

        # Swap
        self.media_files[idx], self.media_files[target_idx] = (
            self.media_files[target_idx],
            self.media_files[idx],
        )

        # Update listbox
        self.file_listbox.delete(idx)
        self.file_listbox.insert(target_idx, _listbox_display(self.media_files[target_idx]))

        self.file_listbox.selection_clear(0, tk.END)
        self.file_listbox.selection_set(target_idx)
        self.selected_indices = [target_idx]

        if idx == self.current_preview_index:
            self.current_preview_index = target_idx
            self.update_preview()

    # ------------------------------------------------------------------
    # Selection and preview
    # ------------------------------------------------------------------

    def on_file_select(self, event):
        self.update_selected_indices()
        if len(self.selected_indices) == 1:
            self.current_preview_index = self.selected_indices[0]
            self.update_preview()
            self._show_selected_info()

    def _show_selected_info(self):
        """If a video is selected, display basic info below the preview."""
        if not self.selected_indices:
            self.video_info_label.config(text="")
            return
        idx = self.selected_indices[0]
        if idx >= len(self.media_files):
            return
        entry = self.media_files[idx]
        if entry["type"] == "video":
            # Try to show video info (non-blocking)
            path = entry["path"]
            def _fetch():
                try:
                    info = video_ops.get_video_info(path)
                    dur = format_duration(info["duration"])
                    txt = (f"Video: {info['width']}x{info['height']}  |  "
                           f"{info['fps']:.1f} fps  |  {dur}  |  "
                           f"Codec: {info['codec']}")
                    self.root.after(0, self.video_info_label.config, {"text": txt})
                except Exception:
                    self.root.after(0, self.video_info_label.config,
                                   {"text": f"Video: {os.path.basename(path)}"})
            threading.Thread(target=_fetch, daemon=True).start()
        else:
            self.video_info_label.config(text="")

    def update_selected_indices(self):
        self.selected_indices = list(self.file_listbox.curselection())

    def preview_current(self):
        if self.media_files:
            self.update_preview()

    def preview_first(self):
        if self.media_files:
            self.current_preview_index = 0
            self.update_preview()

    def preview_previous(self):
        if self.media_files:
            self.current_preview_index = max(0, self.current_preview_index - 1)
            self.update_preview()

    def preview_next(self):
        if self.media_files:
            self.current_preview_index = min(len(self.media_files) - 1,
                                             self.current_preview_index + 1)
            self.update_preview()

    def preview_last(self):
        if self.media_files:
            self.current_preview_index = len(self.media_files) - 1
            self.update_preview()

    def update_preview(self):
        if not self.media_files:
            self.preview_canvas.delete("all")
            self.preview_label.config(text="0/0")
            return

        if self.current_preview_index >= len(self.media_files):
            self.current_preview_index = len(self.media_files) - 1

        entry = self.media_files[self.current_preview_index]
        path = entry["path"]

        if entry["type"] == "video":
            self._preview_video_thumbnail(path)
        else:
            self._preview_image(path)

        self.preview_label.config(
            text=f"{self.current_preview_index + 1}/{len(self.media_files)}"
        )

    def _preview_image(self, image_path):
        try:
            img = Image.open(image_path)

            canvas_width = self.preview_canvas.winfo_width()
            canvas_height = self.preview_canvas.winfo_height()

            if canvas_width <= 1 or canvas_height <= 1:
                self.preview_canvas.after(100, self.update_preview)
                return

            img_width, img_height = img.size
            scale = min(canvas_width / img_width, canvas_height / img_height)
            new_width = int(img_width * scale)
            new_height = int(img_height * scale)

            img_resized = img.resize((new_width, new_height), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img_resized)
            self.current_photo = photo

            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(
                canvas_width // 2, canvas_height // 2,
                image=photo, anchor=tk.CENTER,
            )

            img_info = f"{os.path.basename(image_path)} - {img_width}x{img_height}"
            self.status_var.set(img_info)

        except Exception as e:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                self.preview_canvas.winfo_width() // 2,
                self.preview_canvas.winfo_height() // 2,
                text=f"Error loading image: {e}",
                fill="white",
            )

    def _preview_video_thumbnail(self, video_path):
        """Extract the first frame from a video and show it in the preview canvas."""
        try:
            cap = cv2.VideoCapture(video_path)
            ret, frame = cap.read()
            cap.release()

            if not ret or frame is None:
                raise RuntimeError("Could not read first frame")

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)

            canvas_width = self.preview_canvas.winfo_width()
            canvas_height = self.preview_canvas.winfo_height()

            if canvas_width <= 1 or canvas_height <= 1:
                self.preview_canvas.after(100, self.update_preview)
                return

            img_width, img_height = img.size
            scale = min(canvas_width / img_width, canvas_height / img_height)
            new_width = int(img_width * scale)
            new_height = int(img_height * scale)

            img_resized = img.resize((new_width, new_height), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img_resized)
            self.current_photo = photo

            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(
                canvas_width // 2, canvas_height // 2,
                image=photo, anchor=tk.CENTER,
            )

            self.status_var.set(f"[VIDEO] {os.path.basename(video_path)} - {img_width}x{img_height}")

        except Exception as e:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                self.preview_canvas.winfo_width() // 2,
                self.preview_canvas.winfo_height() // 2,
                text=f"Error loading video thumbnail: {e}",
                fill="white",
            )

    # ------------------------------------------------------------------
    # Custom dialog helpers (icon-aware)
    # ------------------------------------------------------------------

    def custom_askinteger(self, title, prompt, **kw):
        return simpledialog.askinteger(title, prompt, parent=self.root, **kw)

    def custom_askstring(self, title, prompt, **kw):
        return simpledialog.askstring(title, prompt, parent=self.root, **kw)

    # ------------------------------------------------------------------
    # Preview video creation
    # ------------------------------------------------------------------

    def create_preview(self):
        images = self.image_files
        if len(images) < 2:
            messagebox.showinfo("Preview", "Need at least 2 images to create a preview.")
            return

        # FPS dialog
        fps_dialog = tk.Toplevel(self.root)
        fps_dialog.title("Preview FPS")
        fps_dialog.geometry("300x120")
        fps_dialog.transient(self.root)
        fps_dialog.grab_set()
        fps_dialog.resizable(False, False)

        frame = ttk.Frame(fps_dialog, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Enter frames per second for preview:").pack(anchor=tk.W, pady=(0, 10))

        fps_var = tk.IntVar(value=self.output_settings["fps"])
        fps_spinbox = ttk.Spinbox(frame, from_=1, to=60, textvariable=fps_var, width=10)
        fps_spinbox.pack(anchor=tk.W, pady=(0, 10))

        preview_fps = [None]

        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X)

        def on_ok():
            try:
                value = int(fps_var.get())
                if 1 <= value <= 60:
                    preview_fps[0] = value
                    fps_dialog.destroy()
                else:
                    messagebox.showwarning("Invalid Input", "Value must be between 1 and 60.")
            except ValueError:
                messagebox.showwarning("Invalid Input", "Please enter a valid number.")

        def on_cancel():
            fps_dialog.destroy()

        ttk.Button(button_frame, text="OK", command=on_ok).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=on_cancel).pack(side=tk.RIGHT, padx=5)

        fps_spinbox.focus_set()

        fps_dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - fps_dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - fps_dialog.winfo_height()) // 2
        fps_dialog.geometry(f"+{x}+{y}")

        self.root.wait_window(fps_dialog)

        chosen_fps = preview_fps[0]
        if not chosen_fps:
            return

        temp_output = os.path.join(os.path.expanduser("~"), "sim_preview_temp.mp4")
        preview_files = images[:min(100, len(images))]

        progress = ProgressDialog(self.root, "Creating Preview", maximum=len(preview_files))

        def _thread():
            try:
                first_img = cv2.imread(preview_files[0])
                if first_img is None:
                    raise RuntimeError(f"Cannot read image: {preview_files[0]}")
                height, width = first_img.shape[:2]
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                out = cv2.VideoWriter(temp_output, fourcc, chosen_fps, (width, height))

                for i, img_path in enumerate(preview_files):
                    if progress.cancelled:
                        out.release()
                        return
                    self.root.after(0, progress.update_progress, i + 1,
                                    f"Frame {i+1}/{len(preview_files)}")
                    img = cv2.imread(img_path)
                    if img is not None:
                        out.write(img)

                out.release()
                self.root.after(0, progress.destroy)
                self.play_output_file(temp_output)

            except Exception as e:
                self.root.after(0, progress.destroy)
                self.root.after(0, messagebox.showerror, "Error", f"Failed to create preview: {e}")

        threading.Thread(target=_thread, daemon=True).start()

    # ------------------------------------------------------------------
    # Output settings dialog
    # ------------------------------------------------------------------

    def show_output_settings(self):
        settings = tk.Toplevel(self.root)
        settings.title("Output Settings")
        settings.geometry("400x300")
        settings.transient(self.root)
        settings.grab_set()

        frame = ttk.Frame(settings, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Frames Per Second:").grid(row=0, column=0, sticky=tk.W, pady=5)
        fps_var = tk.StringVar(value=str(self.output_settings["fps"]))
        ttk.Spinbox(frame, from_=1, to=120, textvariable=fps_var, width=10).grid(row=0, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Output Format:").grid(row=1, column=0, sticky=tk.W, pady=5)
        format_var = tk.StringVar(value=self.output_settings["format"])
        ttk.Combobox(frame, textvariable=format_var, values=["mp4", "avi", "mov", "webm"], width=10).grid(row=1, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Video Codec:").grid(row=2, column=0, sticky=tk.W, pady=5)
        codec_var = tk.StringVar(value=self.output_settings["codec"])
        ttk.Combobox(frame, textvariable=codec_var, values=["H264", "MJPG", "XVID", "VP9"], width=10).grid(row=2, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Quality (0-100):").grid(row=3, column=0, sticky=tk.W, pady=5)
        quality_var = tk.StringVar(value=str(self.output_settings["quality"]))
        ttk.Spinbox(frame, from_=0, to=100, textvariable=quality_var, width=10).grid(row=3, column=1, sticky=tk.W, pady=5)

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=4, column=0, columnspan=2, pady=20)

        def save_settings():
            try:
                self.output_settings["fps"] = int(fps_var.get())
                self.output_settings["format"] = format_var.get()
                self.output_settings["codec"] = codec_var.get()
                self.output_settings["quality"] = int(quality_var.get())
                self.fps_var.set(str(self.output_settings["fps"]))
                self.format_var.set(self.output_settings["format"])
                self.codec_var.set(self.output_settings["codec"])
                settings.destroy()
            except ValueError as e:
                messagebox.showerror("Error", f"Invalid value: {e}")

        ttk.Button(button_frame, text="Save", command=save_settings).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=settings.destroy).pack(side=tk.LEFT, padx=5)

    # ------------------------------------------------------------------
    # Create video from images (original workflow)
    # ------------------------------------------------------------------

    def create_video(self):
        images = self.image_files
        if len(images) < 2:
            messagebox.showinfo("Create Video", "Need at least 2 images to create a video.")
            return

        output_file = filedialog.asksaveasfilename(
            title="Save Video As",
            defaultextension=f".{self.output_settings['format']}",
            filetypes=[
                (f"{self.output_settings['format'].upper()} files",
                 f"*.{self.output_settings['format']}"),
                ("All files", "*.*"),
            ],
        )
        if not output_file:
            return

        progress = ProgressDialog(self.root, "Creating Video", maximum=len(images))

        def _thread():
            try:
                first_img = cv2.imread(images[0])
                if first_img is None:
                    raise RuntimeError(f"Cannot read image: {images[0]}")
                height, width = first_img.shape[:2]

                fmt = self.output_settings["format"]
                codec = self.output_settings["codec"]
                if fmt == "mp4":
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                elif fmt == "avi":
                    fourcc = cv2.VideoWriter_fourcc(*(
                        "MJPG" if codec == "MJPG" else "XVID"))
                elif fmt == "mov":
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                else:
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")

                out = cv2.VideoWriter(
                    output_file, fourcc, self.output_settings["fps"], (width, height))

                for i, img_path in enumerate(images):
                    if progress.cancelled:
                        out.release()
                        return
                    self.root.after(0, progress.update_progress, i + 1,
                                    f"Frame {i+1}/{len(images)}")
                    img = cv2.imread(img_path)
                    if img is not None:
                        out.write(img)

                out.release()
                self.root.after(0, progress.destroy)

                play = messagebox.askyesno(
                    "Success",
                    f"Video created successfully at:\n{output_file}\n\nPlay it now?",
                )
                if play:
                    self.play_output_file(output_file)

            except Exception as e:
                self.root.after(0, progress.destroy)
                self.root.after(0, messagebox.showerror, "Error", f"Failed to create video: {e}")

        threading.Thread(target=_thread, daemon=True).start()

    def play_output_file(self, file_path):
        import platform
        import subprocess as _sp
        try:
            if platform.system() == "Darwin":
                _sp.call(("open", file_path))
            elif platform.system() == "Windows":
                os.startfile(file_path)
            else:
                _sp.call(("xdg-open", file_path))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open file: {e}")

    # ------------------------------------------------------------------
    # Property update callbacks
    # ------------------------------------------------------------------

    def update_fps(self, event=None):
        try:
            self.output_settings["fps"] = int(self.fps_var.get())
        except ValueError:
            self.fps_var.set(str(self.output_settings["fps"]))

    def update_format(self, event=None):
        self.output_settings["format"] = self.format_var.get()

    def update_codec(self, event=None):
        self.output_settings["codec"] = self.codec_var.get()

    # ==================================================================
    # VIDEO OPERATIONS (ffmpeg-powered)
    # ==================================================================

    def _run_video_op(self, title, operation_fn, done_msg=None):
        """Generic helper: run *operation_fn* in a background thread with a
        ProgressDialog.  *operation_fn* receives a progress_callback that
        accepts a float 0-100.  Returns via root.after on completion."""
        progress = ProgressDialog(self.root, title, maximum=100)

        def _cb(pct):
            self.root.after(0, progress.update_progress, pct,
                            f"{pct:.0f}%")

        def _thread():
            try:
                result = operation_fn(_cb)
                self.root.after(0, progress.destroy)
                if done_msg:
                    self.root.after(0, messagebox.showinfo, "Done", done_msg)
                elif result:
                    self.root.after(0, messagebox.showinfo, "Done", str(result))
            except FFmpegNotFoundError as e:
                self.root.after(0, progress.destroy)
                self.root.after(0, messagebox.showerror, "FFmpeg Not Found", str(e))
            except Exception as e:
                self.root.after(0, progress.destroy)
                self.root.after(0, messagebox.showerror, "Error", str(e))

        threading.Thread(target=_thread, daemon=True).start()

    # -- Merge Videos --------------------------------------------------

    def merge_videos(self):
        if not self._require_ffmpeg():
            return

        paths = self._get_selected_video_paths()
        if len(paths) < 2:
            messagebox.showinfo("Merge Videos",
                                "Select at least 2 video files in the list to merge.")
            return

        dlg = MergeOptionsDialog(self.root)
        self.root.wait_window(dlg)
        if dlg.result is None:
            return

        ext = dlg.result["format"]
        output_file = filedialog.asksaveasfilename(
            title="Save Merged Video As",
            defaultextension=f".{ext}",
            filetypes=[(f"{ext.upper()} files", f"*.{ext}"), ("All files", "*.*")],
        )
        if not output_file:
            return

        def op(cb):
            video_ops.merge_videos(paths, output_file, progress_callback=cb)
            return f"Merged video saved to:\n{output_file}"

        self._run_video_op("Merging Videos", op)

    # -- Split Video ---------------------------------------------------

    def split_video(self):
        if not self._require_ffmpeg():
            return
        path = self._get_selected_video_path()
        if not path:
            messagebox.showinfo("Split Video", "Select a video file first.")
            return

        try:
            info = video_ops.get_video_info(path)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read video info: {e}")
            return

        dlg = SplitVideoDialog(self.root, info["duration"])
        self.root.wait_window(dlg)
        if dlg.result is None or not dlg.result:
            return

        output_dir = filedialog.askdirectory(title="Select Output Directory for Segments")
        if not output_dir:
            return

        split_points = dlg.result

        def op(cb):
            result_files = video_ops.split_video(path, output_dir, split_points,
                                                 progress_callback=cb)
            return f"Split into {len(result_files)} segment(s) in:\n{output_dir}"

        self._run_video_op("Splitting Video", op)

    # -- Trim Video ----------------------------------------------------

    def trim_video(self):
        if not self._require_ffmpeg():
            return
        path = self._get_selected_video_path()
        if not path:
            messagebox.showinfo("Trim Video", "Select a video file first.")
            return

        try:
            info = video_ops.get_video_info(path)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read video info: {e}")
            return

        dlg = TrimDialog(self.root, info["duration"])
        self.root.wait_window(dlg)
        if dlg.result is None:
            return

        start_time, end_time = dlg.result
        base, ext = os.path.splitext(path)
        default_name = f"{os.path.basename(base)}_trimmed{ext}"

        output_file = filedialog.asksaveasfilename(
            title="Save Trimmed Video As",
            initialfile=default_name,
            defaultextension=ext,
            filetypes=[("Video files", f"*{ext}"), ("All files", "*.*")],
        )
        if not output_file:
            return

        def op(cb):
            video_ops.trim_video(path, output_file, start_time, end_time,
                                 progress_callback=cb)
            return f"Trimmed video saved to:\n{output_file}"

        self._run_video_op("Trimming Video", op)

    # -- Mute Audio ----------------------------------------------------

    def mute_audio(self):
        if not self._require_ffmpeg():
            return
        path = self._get_selected_video_path()
        if not path:
            messagebox.showinfo("Mute Audio", "Select a video file first.")
            return

        base, ext = os.path.splitext(path)
        default_name = f"{os.path.basename(base)}_muted{ext}"

        output_file = filedialog.asksaveasfilename(
            title="Save Muted Video As",
            initialfile=default_name,
            defaultextension=ext,
            filetypes=[("Video files", f"*{ext}"), ("All files", "*.*")],
        )
        if not output_file:
            return

        def op(cb):
            video_ops.mute_audio(path, output_file, progress_callback=cb)
            return f"Audio removed. Saved to:\n{output_file}"

        self._run_video_op("Removing Audio", op)

    # -- Extract Audio -------------------------------------------------

    def extract_audio(self):
        if not self._require_ffmpeg():
            return
        path = self._get_selected_video_path()
        if not path:
            messagebox.showinfo("Extract Audio", "Select a video file first.")
            return

        base = os.path.splitext(os.path.basename(path))[0]
        output_file = filedialog.asksaveasfilename(
            title="Save Audio As",
            initialfile=f"{base}_audio.aac",
            defaultextension=".aac",
            filetypes=[("AAC audio", "*.aac"), ("MP3 audio", "*.mp3"),
                       ("WAV audio", "*.wav"), ("All files", "*.*")],
        )
        if not output_file:
            return

        def op(cb):
            video_ops.extract_audio(path, output_file, progress_callback=cb)
            return f"Audio extracted to:\n{output_file}"

        self._run_video_op("Extracting Audio", op)

    # -- Add Audio -----------------------------------------------------

    def add_audio(self):
        if not self._require_ffmpeg():
            return
        path = self._get_selected_video_path()
        if not path:
            messagebox.showinfo("Add Audio", "Select a video file first.")
            return

        audio_file = filedialog.askopenfilename(
            title="Select Audio File",
            filetypes=[("Audio files", "*.mp3 *.aac *.wav *.ogg *.flac *.m4a"),
                       ("All files", "*.*")],
        )
        if not audio_file:
            return

        replace = messagebox.askyesno(
            "Replace Audio?",
            "Replace existing audio track?\n\n"
            "Yes = replace original audio\n"
            "No = add as additional audio stream",
        )

        base, ext = os.path.splitext(path)
        default_name = f"{os.path.basename(base)}_with_audio{ext}"

        output_file = filedialog.asksaveasfilename(
            title="Save Video With Audio As",
            initialfile=default_name,
            defaultextension=ext,
            filetypes=[("Video files", f"*{ext}"), ("All files", "*.*")],
        )
        if not output_file:
            return

        def op(cb):
            video_ops.add_audio(path, audio_file, output_file, replace=replace,
                                progress_callback=cb)
            return f"Audio added. Saved to:\n{output_file}"

        self._run_video_op("Adding Audio", op)

    # -- Change Speed --------------------------------------------------

    def change_speed(self):
        if not self._require_ffmpeg():
            return
        path = self._get_selected_video_path()
        if not path:
            messagebox.showinfo("Change Speed", "Select a video file first.")
            return

        dlg = SpeedDialog(self.root)
        self.root.wait_window(dlg)
        if dlg.result is None:
            return

        speed_factor = dlg.result

        base, ext = os.path.splitext(path)
        default_name = f"{os.path.basename(base)}_{speed_factor}x{ext}"

        output_file = filedialog.asksaveasfilename(
            title="Save Speed-Changed Video As",
            initialfile=default_name,
            defaultextension=ext,
            filetypes=[("Video files", f"*{ext}"), ("All files", "*.*")],
        )
        if not output_file:
            return

        def op(cb):
            video_ops.change_speed(path, output_file, speed_factor,
                                   progress_callback=cb)
            return f"Speed changed ({speed_factor}x). Saved to:\n{output_file}"

        self._run_video_op("Changing Speed", op)

    # -- Extract Frames ------------------------------------------------

    def extract_frames(self):
        if not self._require_ffmpeg():
            return
        path = self._get_selected_video_path()
        if not path:
            messagebox.showinfo("Extract Frames", "Select a video file first.")
            return

        try:
            info = video_ops.get_video_info(path)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read video info: {e}")
            return

        dlg = ExtractFramesDialog(self.root, info["fps"])
        self.root.wait_window(dlg)
        if dlg.result is None:
            return

        settings = dlg.result
        output_dir = filedialog.askdirectory(title="Select Output Directory for Frames")
        if not output_dir:
            return

        # Determine fps arg for extract_frames
        extract_fps = None
        if settings["mode"] == "fps":
            extract_fps = settings.get("fps")
        elif settings["mode"] == "nth":
            nth = settings.get("nth", 10)
            if info["fps"] > 0:
                extract_fps = info["fps"] / nth

        fmt = settings.get("format", "png").lower()

        def op(cb):
            result_files = video_ops.extract_frames(
                path, output_dir, fps=extract_fps, format=fmt,
                progress_callback=cb,
            )
            # Optionally add extracted frames to the media list
            self.root.after(0, self._offer_add_extracted_frames, result_files)
            return f"Extracted {len(result_files)} frame(s) to:\n{output_dir}"

        self._run_video_op("Extracting Frames", op)

    def _offer_add_extracted_frames(self, frame_paths):
        if not frame_paths:
            return
        add = messagebox.askyesno(
            "Add Frames?",
            f"Extracted {len(frame_paths)} frames.\n\n"
            "Add them to the media file list?",
        )
        if add:
            existing_paths = {m["path"] for m in self.media_files}
            for fp in frame_paths:
                if fp not in existing_paths:
                    entry = {"path": fp, "type": "image"}
                    self.media_files.append(entry)
                    self.file_listbox.insert(tk.END, _listbox_display(entry))
            self.status_var.set(f"Added {len(frame_paths)} extracted frames")

    # -- Convert Format ------------------------------------------------

    def convert_format(self):
        if not self._require_ffmpeg():
            return
        path = self._get_selected_video_path()
        if not path:
            messagebox.showinfo("Convert Format", "Select a video file first.")
            return

        base = os.path.splitext(os.path.basename(path))[0]
        output_file = filedialog.asksaveasfilename(
            title="Save Converted Video As",
            initialfile=base,
            filetypes=[
                ("MP4", "*.mp4"), ("MKV", "*.mkv"), ("AVI", "*.avi"),
                ("MOV", "*.mov"), ("WebM", "*.webm"), ("All files", "*.*"),
            ],
        )
        if not output_file:
            return

        def op(cb):
            video_ops.convert_format(path, output_file, progress_callback=cb)
            return f"Converted video saved to:\n{output_file}"

        self._run_video_op("Converting Video", op)

    # -- Create GIF ----------------------------------------------------

    def create_gif(self):
        if not self._require_ffmpeg():
            return
        path = self._get_selected_video_path()
        if not path:
            messagebox.showinfo("Create GIF", "Select a video file first.")
            return

        fps = simpledialog.askinteger("GIF FPS", "Frames per second for the GIF:",
                                      initialvalue=10, minvalue=1, maxvalue=30,
                                      parent=self.root)
        if fps is None:
            return

        width = simpledialog.askinteger("GIF Width", "Width in pixels (height auto):",
                                        initialvalue=480, minvalue=100, maxvalue=3840,
                                        parent=self.root)
        if width is None:
            return

        base = os.path.splitext(os.path.basename(path))[0]
        output_file = filedialog.asksaveasfilename(
            title="Save GIF As",
            initialfile=f"{base}.gif",
            defaultextension=".gif",
            filetypes=[("GIF files", "*.gif"), ("All files", "*.*")],
        )
        if not output_file:
            return

        def op(cb):
            video_ops.create_gif(path, output_file, fps=fps, width=width,
                                 progress_callback=cb)
            return f"GIF created at:\n{output_file}"

        self._run_video_op("Creating GIF", op)

    # ==================================================================
    # METADATA OPERATIONS
    # ==================================================================

    def view_metadata(self):
        if not self._require_ffmpeg():
            return
        path = self._get_selected_video_path()
        if not path:
            messagebox.showinfo("View Metadata", "Select a video file first.")
            return

        try:
            info = video_ops.get_video_info(path)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read video info: {e}")
            return

        # Build a friendly info dict for the dialog
        display = {
            "duration": format_duration(info["duration"]),
            "resolution": f"{info['width']}x{info['height']}",
            "fps": f"{info['fps']:.2f}",
            "codec": info["codec"],
            "audio": info["audio_codec"] or "None",
            "bitrate": f"{info['bitrate'] // 1000} kbps" if info["bitrate"] else "N/A",
            "file_size": self._format_file_size(info["file_size"]),
        }
        VideoInfoDialog(self.root, display)

    def edit_metadata(self):
        if not self._require_ffmpeg():
            return
        path = self._get_selected_video_path()
        if not path:
            messagebox.showinfo("Edit Metadata", "Select a video file first.")
            return

        try:
            existing = video_ops.get_metadata(path)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read metadata: {e}")
            return

        dlg = MetadataDialog(self.root, existing)
        self.root.wait_window(dlg)
        if dlg.result is None:
            return

        new_meta = dlg.result

        base, ext = os.path.splitext(path)
        default_name = f"{os.path.basename(base)}_meta{ext}"

        output_file = filedialog.asksaveasfilename(
            title="Save Video With Updated Metadata",
            initialfile=default_name,
            defaultextension=ext,
            filetypes=[("Video files", f"*{ext}"), ("All files", "*.*")],
        )
        if not output_file:
            return

        def op(cb):
            video_ops.set_metadata(path, output_file, new_meta,
                                   progress_callback=cb)
            return f"Metadata updated. Saved to:\n{output_file}"

        self._run_video_op("Writing Metadata", op)

    def strip_metadata(self):
        if not self._require_ffmpeg():
            return
        path = self._get_selected_video_path()
        if not path:
            messagebox.showinfo("Strip Metadata", "Select a video file first.")
            return

        base, ext = os.path.splitext(path)
        default_name = f"{os.path.basename(base)}_stripped{ext}"

        output_file = filedialog.asksaveasfilename(
            title="Save Stripped Video As",
            initialfile=default_name,
            defaultextension=ext,
            filetypes=[("Video files", f"*{ext}"), ("All files", "*.*")],
        )
        if not output_file:
            return

        def op(cb):
            video_ops.strip_metadata(path, output_file, progress_callback=cb)
            return f"Metadata stripped. Saved to:\n{output_file}"

        self._run_video_op("Stripping Metadata", op)

    @staticmethod
    def _format_file_size(size_bytes):
        if size_bytes <= 0:
            return "N/A"
        for unit in ("B", "KB", "MB", "GB"):
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

    # ==================================================================
    # FILTERS (image processing)
    # ==================================================================

    def apply_filter(self, filter_name):
        if not self.selected_indices:
            messagebox.showinfo("Filter", "Please select images to apply the filter to.")
            return

        dispatch = {
            "crop": self.show_crop_dialog,
            "resize": self.show_resize_dialog,
            "rotate": self.show_rotate_dialog,
            "brightness": self.show_brightness_dialog,
            "contrast": self.show_contrast_dialog,
            "grayscale": self.apply_grayscale,
            "text_overlay": self.show_text_overlay_dialog,
            "scale_bar": self.show_scale_bar_dialog,
            "timestamp": self.show_timestamp_dialog,
        }
        handler = dispatch.get(filter_name)
        if handler:
            handler()

    def _get_selected_image_paths(self):
        """Return the paths of all selected image entries."""
        return [
            self.media_files[i]["path"]
            for i in self.selected_indices
            if i < len(self.media_files) and self.media_files[i]["type"] == "image"
        ]

    def _apply_cv2_filter_to_selected(self, filter_fn, description="filter"):
        """Apply *filter_fn(img) -> img* to every selected image and
        overwrite the file.  Shows a progress bar."""
        paths = self._get_selected_image_paths()
        if not paths:
            messagebox.showinfo("Filter", "No images selected.")
            return

        progress = ProgressDialog(self.root, f"Applying {description}",
                                  maximum=len(paths))

        def _thread():
            try:
                for i, p in enumerate(paths):
                    if progress.cancelled:
                        break
                    img = cv2.imread(p)
                    if img is None:
                        continue
                    result = filter_fn(img)
                    cv2.imwrite(p, result)
                    self.root.after(0, progress.update_progress, i + 1,
                                    f"{i+1}/{len(paths)}")
                self.root.after(0, progress.destroy)
                self.root.after(0, self.update_preview)
                self.root.after(0, self.status_var.set,
                                f"{description} applied to {len(paths)} image(s)")
            except Exception as e:
                self.root.after(0, progress.destroy)
                self.root.after(0, messagebox.showerror, "Error", str(e))

        threading.Thread(target=_thread, daemon=True).start()

    # -- Crop dialog ---------------------------------------------------

    def show_crop_dialog(self):
        crop = tk.Toplevel(self.root)
        crop.title("Crop Images")
        crop.geometry("300x220")
        crop.transient(self.root)
        crop.grab_set()

        frame = ttk.Frame(crop, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Left:").grid(row=0, column=0, sticky=tk.W, pady=5)
        left_var = tk.StringVar(value="0")
        ttk.Entry(frame, textvariable=left_var, width=10).grid(row=0, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Top:").grid(row=1, column=0, sticky=tk.W, pady=5)
        top_var = tk.StringVar(value="0")
        ttk.Entry(frame, textvariable=top_var, width=10).grid(row=1, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Right:").grid(row=2, column=0, sticky=tk.W, pady=5)
        right_var = tk.StringVar(value="100")
        ttk.Entry(frame, textvariable=right_var, width=10).grid(row=2, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Bottom:").grid(row=3, column=0, sticky=tk.W, pady=5)
        bottom_var = tk.StringVar(value="100")
        ttk.Entry(frame, textvariable=bottom_var, width=10).grid(row=3, column=1, sticky=tk.W, pady=5)

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=4, column=0, columnspan=2, pady=10)

        def apply_crop():
            try:
                left = int(left_var.get())
                top = int(top_var.get())
                right = int(right_var.get())
                bottom = int(bottom_var.get())
                crop.destroy()
                self._apply_cv2_filter_to_selected(
                    lambda img: img[top:bottom, left:right], "Crop")
            except ValueError as e:
                messagebox.showerror("Error", f"Invalid value: {e}")

        ttk.Button(button_frame, text="Apply", command=apply_crop).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=crop.destroy).pack(side=tk.LEFT, padx=5)

    # -- Resize dialog -------------------------------------------------

    def show_resize_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Resize Images")
        dlg.geometry("300x180")
        dlg.transient(self.root)
        dlg.grab_set()

        frame = ttk.Frame(dlg, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Width:").grid(row=0, column=0, sticky=tk.W, pady=5)
        width_var = tk.StringVar(value="640")
        ttk.Entry(frame, textvariable=width_var, width=10).grid(row=0, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Height:").grid(row=1, column=0, sticky=tk.W, pady=5)
        height_var = tk.StringVar(value="480")
        ttk.Entry(frame, textvariable=height_var, width=10).grid(row=1, column=1, sticky=tk.W, pady=5)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=10)

        def apply_resize():
            try:
                w = int(width_var.get())
                h = int(height_var.get())
                if w <= 0 or h <= 0:
                    raise ValueError("Dimensions must be positive")
                dlg.destroy()
                self._apply_cv2_filter_to_selected(
                    lambda img: cv2.resize(img, (w, h), interpolation=cv2.INTER_LANCZOS4),
                    "Resize",
                )
            except ValueError as e:
                messagebox.showerror("Error", f"Invalid value: {e}")

        ttk.Button(btn_frame, text="Apply", command=apply_resize).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy).pack(side=tk.LEFT, padx=5)

    # -- Rotate dialog -------------------------------------------------

    def show_rotate_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Rotate Images")
        dlg.geometry("300x150")
        dlg.transient(self.root)
        dlg.grab_set()

        frame = ttk.Frame(dlg, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Angle (degrees):").grid(row=0, column=0, sticky=tk.W, pady=5)
        angle_var = tk.StringVar(value="90")
        ttk.Combobox(frame, textvariable=angle_var,
                     values=["90", "180", "270", "-90"], width=8).grid(
            row=0, column=1, sticky=tk.W, pady=5)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=1, column=0, columnspan=2, pady=10)

        def apply_rotate():
            try:
                angle = float(angle_var.get())
                dlg.destroy()

                def _rot(img):
                    h, w = img.shape[:2]
                    center = (w // 2, h // 2)
                    M = cv2.getRotationMatrix2D(center, angle, 1.0)
                    cos = abs(M[0, 0])
                    sin = abs(M[0, 1])
                    new_w = int(h * sin + w * cos)
                    new_h = int(h * cos + w * sin)
                    M[0, 2] += (new_w - w) / 2
                    M[1, 2] += (new_h - h) / 2
                    return cv2.warpAffine(img, M, (new_w, new_h))

                self._apply_cv2_filter_to_selected(_rot, "Rotate")
            except ValueError as e:
                messagebox.showerror("Error", f"Invalid value: {e}")

        ttk.Button(btn_frame, text="Apply", command=apply_rotate).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy).pack(side=tk.LEFT, padx=5)

    # -- Brightness dialog ---------------------------------------------

    def show_brightness_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Adjust Brightness")
        dlg.geometry("320x150")
        dlg.transient(self.root)
        dlg.grab_set()

        frame = ttk.Frame(dlg, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Brightness offset (-255 to 255):").pack(anchor=tk.W)
        bright_var = tk.IntVar(value=0)
        scale = ttk.Scale(frame, from_=-255, to=255, orient=tk.HORIZONTAL,
                          variable=bright_var)
        scale.pack(fill=tk.X, pady=5)

        val_label = ttk.Label(frame, text="0")
        val_label.pack(anchor=tk.E)
        scale.config(command=lambda v: val_label.config(text=f"{int(float(v))}"))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=5)

        def apply_brightness():
            offset = bright_var.get()
            dlg.destroy()
            self._apply_cv2_filter_to_selected(
                lambda img: cv2.convertScaleAbs(img, alpha=1.0, beta=offset),
                "Brightness",
            )

        ttk.Button(btn_frame, text="Apply", command=apply_brightness).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy).pack(side=tk.RIGHT, padx=5)

    # -- Contrast dialog -----------------------------------------------

    def show_contrast_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Adjust Contrast")
        dlg.geometry("320x150")
        dlg.transient(self.root)
        dlg.grab_set()

        frame = ttk.Frame(dlg, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Contrast factor (0.1 to 3.0):").pack(anchor=tk.W)
        contrast_var = tk.DoubleVar(value=1.0)
        scale = ttk.Scale(frame, from_=0.1, to=3.0, orient=tk.HORIZONTAL,
                          variable=contrast_var)
        scale.pack(fill=tk.X, pady=5)

        val_label = ttk.Label(frame, text="1.00")
        val_label.pack(anchor=tk.E)
        scale.config(command=lambda v: val_label.config(text=f"{float(v):.2f}"))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=5)

        def apply_contrast():
            factor = contrast_var.get()
            dlg.destroy()
            self._apply_cv2_filter_to_selected(
                lambda img: cv2.convertScaleAbs(img, alpha=factor, beta=0),
                "Contrast",
            )

        ttk.Button(btn_frame, text="Apply", command=apply_contrast).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy).pack(side=tk.RIGHT, padx=5)

    # -- Grayscale -----------------------------------------------------

    def apply_grayscale(self):
        def _to_gray(img):
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

        self._apply_cv2_filter_to_selected(_to_gray, "Grayscale")

    # -- Text overlay dialog -------------------------------------------

    def show_text_overlay_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Text Overlay")
        dlg.geometry("350x250")
        dlg.transient(self.root)
        dlg.grab_set()

        frame = ttk.Frame(dlg, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Text:").grid(row=0, column=0, sticky=tk.W, pady=5)
        text_var = tk.StringVar(value="Sample Text")
        ttk.Entry(frame, textvariable=text_var, width=30).grid(row=0, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="X position:").grid(row=1, column=0, sticky=tk.W, pady=5)
        x_var = tk.StringVar(value="10")
        ttk.Entry(frame, textvariable=x_var, width=10).grid(row=1, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Y position:").grid(row=2, column=0, sticky=tk.W, pady=5)
        y_var = tk.StringVar(value="30")
        ttk.Entry(frame, textvariable=y_var, width=10).grid(row=2, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Font scale:").grid(row=3, column=0, sticky=tk.W, pady=5)
        scale_var = tk.StringVar(value="1.0")
        ttk.Entry(frame, textvariable=scale_var, width=10).grid(row=3, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Color (B,G,R):").grid(row=4, column=0, sticky=tk.W, pady=5)
        color_var = tk.StringVar(value="255,255,255")
        ttk.Entry(frame, textvariable=color_var, width=15).grid(row=4, column=1, sticky=tk.W, pady=5)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=5, column=0, columnspan=2, pady=10)

        def apply_text():
            try:
                text = text_var.get()
                x = int(x_var.get())
                y = int(y_var.get())
                fs = float(scale_var.get())
                color = tuple(int(c.strip()) for c in color_var.get().split(","))
                dlg.destroy()

                def _overlay(img):
                    return cv2.putText(
                        img.copy(), text, (x, y),
                        cv2.FONT_HERSHEY_SIMPLEX, fs, color, 2, cv2.LINE_AA,
                    )

                self._apply_cv2_filter_to_selected(_overlay, "Text Overlay")
            except Exception as e:
                messagebox.showerror("Error", f"Invalid input: {e}")

        ttk.Button(btn_frame, text="Apply", command=apply_text).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy).pack(side=tk.LEFT, padx=5)

    # -- Scale bar dialog ----------------------------------------------

    def show_scale_bar_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Scale Bar")
        dlg.geometry("350x250")
        dlg.transient(self.root)
        dlg.grab_set()

        frame = ttk.Frame(dlg, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Bar length (px):").grid(row=0, column=0, sticky=tk.W, pady=5)
        len_var = tk.StringVar(value="100")
        ttk.Entry(frame, textvariable=len_var, width=10).grid(row=0, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Label (e.g. '100 um'):").grid(row=1, column=0, sticky=tk.W, pady=5)
        label_var = tk.StringVar(value="100 um")
        ttk.Entry(frame, textvariable=label_var, width=15).grid(row=1, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="X position:").grid(row=2, column=0, sticky=tk.W, pady=5)
        x_var = tk.StringVar(value="20")
        ttk.Entry(frame, textvariable=x_var, width=10).grid(row=2, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Y position:").grid(row=3, column=0, sticky=tk.W, pady=5)
        y_var = tk.StringVar(value="20")
        ttk.Entry(frame, textvariable=y_var, width=10).grid(row=3, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Bar thickness:").grid(row=4, column=0, sticky=tk.W, pady=5)
        thick_var = tk.StringVar(value="5")
        ttk.Entry(frame, textvariable=thick_var, width=10).grid(row=4, column=1, sticky=tk.W, pady=5)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=5, column=0, columnspan=2, pady=10)

        def apply_scale_bar():
            try:
                bar_len = int(len_var.get())
                label = label_var.get()
                x = int(x_var.get())
                y = int(y_var.get())
                thickness = int(thick_var.get())
                dlg.destroy()

                def _bar(img):
                    out = img.copy()
                    # Draw the bar line
                    cv2.line(out, (x, y), (x + bar_len, y), (255, 255, 255), thickness)
                    # End caps
                    cap_h = thickness * 2
                    cv2.line(out, (x, y - cap_h), (x, y + cap_h), (255, 255, 255), thickness)
                    cv2.line(out, (x + bar_len, y - cap_h), (x + bar_len, y + cap_h),
                             (255, 255, 255), thickness)
                    # Label
                    cv2.putText(out, label, (x, y - cap_h - 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1,
                                cv2.LINE_AA)
                    return out

                self._apply_cv2_filter_to_selected(_bar, "Scale Bar")
            except Exception as e:
                messagebox.showerror("Error", f"Invalid input: {e}")

        ttk.Button(btn_frame, text="Apply", command=apply_scale_bar).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy).pack(side=tk.LEFT, padx=5)

    # -- Timestamp dialog ----------------------------------------------

    def show_timestamp_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Timestamp Overlay")
        dlg.geometry("350x220")
        dlg.transient(self.root)
        dlg.grab_set()

        frame = ttk.Frame(dlg, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Start time (s):").grid(row=0, column=0, sticky=tk.W, pady=5)
        start_var = tk.StringVar(value="0")
        ttk.Entry(frame, textvariable=start_var, width=10).grid(row=0, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Time step per frame (s):").grid(row=1, column=0, sticky=tk.W, pady=5)
        step_var = tk.StringVar(value="1.0")
        ttk.Entry(frame, textvariable=step_var, width=10).grid(row=1, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Format string:").grid(row=2, column=0, sticky=tk.W, pady=5)
        fmt_var = tk.StringVar(value="t = {:.1f} s")
        ttk.Entry(frame, textvariable=fmt_var, width=20).grid(row=2, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Position (x, y):").grid(row=3, column=0, sticky=tk.W, pady=5)
        pos_var = tk.StringVar(value="10, 30")
        ttk.Entry(frame, textvariable=pos_var, width=15).grid(row=3, column=1, sticky=tk.W, pady=5)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=10)

        def apply_timestamp():
            try:
                start_t = float(start_var.get())
                step = float(step_var.get())
                fmt_str = fmt_var.get()
                pos_parts = pos_var.get().split(",")
                px = int(pos_parts[0].strip())
                py = int(pos_parts[1].strip())
                dlg.destroy()

                paths = self._get_selected_image_paths()
                if not paths:
                    messagebox.showinfo("Timestamp", "No images selected.")
                    return

                progress = ProgressDialog(self.root, "Applying Timestamp",
                                          maximum=len(paths))

                def _thread():
                    try:
                        for i, p in enumerate(paths):
                            if progress.cancelled:
                                break
                            img = cv2.imread(p)
                            if img is None:
                                continue
                            t = start_t + i * step
                            text = fmt_str.format(t)
                            cv2.putText(img, text, (px, py),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                                        (255, 255, 255), 2, cv2.LINE_AA)
                            cv2.imwrite(p, img)
                            self.root.after(0, progress.update_progress, i + 1,
                                            f"{i+1}/{len(paths)}")
                        self.root.after(0, progress.destroy)
                        self.root.after(0, self.update_preview)
                        self.root.after(0, self.status_var.set,
                                        f"Timestamp applied to {len(paths)} image(s)")
                    except Exception as e:
                        self.root.after(0, progress.destroy)
                        self.root.after(0, messagebox.showerror, "Error", str(e))

                threading.Thread(target=_thread, daemon=True).start()

            except Exception as e:
                messagebox.showerror("Error", f"Invalid input: {e}")

        ttk.Button(btn_frame, text="Apply", command=apply_timestamp).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy).pack(side=tk.LEFT, padx=5)

    # ==================================================================
    # TOOLS
    # ==================================================================

    def batch_process(self):
        batch = tk.Toplevel(self.root)
        batch.title("Batch Process")
        batch.geometry("500x400")
        batch.transient(self.root)
        batch.grab_set()

        frame = ttk.Frame(batch, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Batch Processing", font=("TkDefaultFont", 11, "bold")).pack(
            anchor=tk.W, pady=(0, 10))
        ttk.Label(frame, text="Apply a filter to all images in the list.").pack(anchor=tk.W, pady=(0, 10))

        filter_var = tk.StringVar(value="grayscale")
        filters = ["grayscale", "resize", "rotate", "brightness", "contrast"]
        ttk.Label(frame, text="Select filter:").pack(anchor=tk.W)
        combo = ttk.Combobox(frame, textvariable=filter_var, values=filters, state="readonly", width=20)
        combo.pack(anchor=tk.W, pady=5)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=10)

        def run_batch():
            batch.destroy()
            # Select all items then apply the chosen filter
            self.file_listbox.selection_set(0, tk.END)
            self.update_selected_indices()
            self.apply_filter(filter_var.get())

        ttk.Button(btn_frame, text="Run", command=run_batch).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=batch.destroy).pack(side=tk.LEFT, padx=5)

    def export_file_list(self):
        if not self.media_files:
            messagebox.showinfo("Export List", "No files to export.")
            return

        filename = filedialog.asksaveasfilename(
            title="Export File List",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not filename:
            return

        try:
            with open(filename, "w") as f:
                for entry in self.media_files:
                    f.write(f"{entry['path']}\n")
            self.status_var.set(f"File list exported to {os.path.basename(filename)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export file list: {e}")

    def import_file_list(self):
        filename = filedialog.askopenfilename(
            title="Import File List",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not filename:
            return

        try:
            with open(filename, "r") as f:
                file_paths = [line.strip() for line in f if line.strip()]

            self.media_files = []
            self.file_listbox.delete(0, tk.END)

            for path in file_paths:
                if os.path.isfile(path):
                    mtype = "video" if _is_video_file(path) else "image"
                    entry = {"path": path, "type": mtype}
                    self.media_files.append(entry)
                    self.file_listbox.insert(tk.END, _listbox_display(entry))

            if self.media_files:
                self.current_preview_index = 0
                self.update_preview()

            self.status_var.set(f"Imported {len(self.media_files)} file(s) from list")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to import file list: {e}")

    # ==================================================================
    # HELP
    # ==================================================================

    def show_documentation(self):
        help_window = tk.Toplevel(self.root)
        help_window.title("SimMovieMaker Documentation")
        help_window.geometry("600x450")

        text = tk.Text(help_window, wrap=tk.WORD, padx=10, pady=10)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(help_window, orient=tk.VERTICAL, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.config(yscrollcommand=scrollbar.set)

        text.insert(tk.END, """SimMovieMaker v2.0 Documentation
==================================

SimMovieMaker is a tool for creating movies from simulation image
snapshots and performing video file operations.

IMAGE WORKFLOW
--------------
1. Import your simulation images using File > Import Images
   or File > Import Sequence.
2. Arrange images in the desired order using the Up/Down buttons.
3. Set output properties (FPS, format, codec).
4. Use Preview to check how the movie will look.
5. Click Create Video to generate the final output.

VIDEO OPERATIONS (requires FFmpeg)
-----------------------------------
- Merge Videos: combine multiple videos into one.
- Split Video: split a video at defined time points.
- Trim Video: remove start/end portions.
- Audio operations: mute, extract, or add audio tracks.
- Change Speed: speed up or slow down playback.
- Extract Frames: pull individual frames as images.
- Convert Format: transcode between video formats.
- Create GIF: convert a video to an animated GIF.

METADATA
--------
- View, edit, or strip metadata from video files.

FILTERS
-------
- Crop, Resize, Rotate
- Brightness, Contrast, Grayscale
- Text Overlay, Scale Bar, Timestamp

KEYBOARD SHORTCUTS
------------------
- Ctrl+N: New Project
- Ctrl+O: Open Project
- Ctrl+S: Save Project
- Ctrl+I: Import Images
- Delete: Remove selected items
""")
        text.config(state=tk.DISABLED)

    def show_about(self):
        messagebox.showinfo(
            "About SimMovieMaker",
            "SimMovieMaker v2.0\n\n"
            "Create movies from simulation snapshots and edit video files.\n\n"
            "Built with Python, Tkinter, OpenCV, and FFmpeg.",
        )

    def show_ffmpeg_status(self):
        status = check_ffmpeg()
        if status["available"]:
            text = (
                f"FFmpeg is available.\n\n"
                f"ffmpeg:  {status['ffmpeg_path']}\n"
                f"ffprobe: {status['ffprobe_path']}\n\n"
                f"Version: {status['version']}"
            )
        else:
            text = "FFmpeg was NOT found on this system.\n\n" + get_ffmpeg_help_text()
        FFmpegHelpDialog(self.root, text)

    def check_for_ffmpeg(self):
        """Manually re-check for ffmpeg and update the status bar."""
        from .ffmpeg_utils import _ffmpeg_path_cache, _ffprobe_path_cache
        import simmovimaker.ffmpeg_utils as _fu
        # Reset caches to force a fresh search
        _fu._ffmpeg_path_cache = None
        _fu._ffprobe_path_cache = None
        self.status_var.set("Checking for FFmpeg...")
        threading.Thread(target=self._check_ffmpeg_async, daemon=True).start()


# ---------------------------------------------------------------------------
# Entry point (for running the GUI directly)
# ---------------------------------------------------------------------------

def main():
    root = tk.Tk()

    # Set minimum size
    root.minsize(800, 600)

    # Create and run the application
    app = SimMovieMaker(root)

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
