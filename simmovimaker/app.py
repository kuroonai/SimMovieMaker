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
import queue
import time
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

THUMB_W = 80
THUMB_H = 60
THUMB_PAD = 4


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


def _format_time_short(seconds):
    """Format seconds as M:SS or H:MM:SS."""
    if seconds is None or seconds < 0:
        seconds = 0
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ---------------------------------------------------------------------------
# ThumbnailStrip - horizontal scrollable thumbnail timeline
# ---------------------------------------------------------------------------

class ThumbnailStrip:
    """Horizontal scrollable strip of thumbnails with background loading."""

    def __init__(self, parent, on_select_callback):
        self._on_select = on_select_callback
        self._thumb_cache = {}          # key -> ImageTk.PhotoImage
        self._items = []                # list of dicts describing each thumb slot
        self._current_index = -1
        self._generation = 0            # incremented on rebuild to cancel stale work
        self._work_queue = queue.Queue()
        self._placeholder = None        # gray placeholder PhotoImage

        # -- widgets --
        self.frame = ttk.Frame(parent)

        self.canvas = tk.Canvas(self.frame, height=THUMB_H + THUMB_PAD * 2 + 18,
                                bg="#2b2b2b", highlightthickness=0)
        self.canvas.pack(side=tk.TOP, fill=tk.X, expand=True)

        self.scrollbar = ttk.Scrollbar(self.frame, orient=tk.HORIZONTAL,
                                       command=self.canvas.xview)
        self.scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.config(xscrollcommand=self.scrollbar.set)

        self.canvas.bind("<ButtonRelease-1>", self._on_click)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Shift-MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Configure>", lambda e: self._load_visible())

        # Start the background worker
        self._worker_thread = threading.Thread(target=self._thumb_worker,
                                               daemon=True)
        self._worker_thread.start()

    # -- public API --

    def set_items(self, items):
        """items: list of dicts with 'path', 'type', and optionally 'time' (seconds)."""
        self._generation += 1
        self._thumb_cache.clear()
        self._items = list(items)
        self._current_index = -1
        # drain queue
        while not self._work_queue.empty():
            try:
                self._work_queue.get_nowait()
            except queue.Empty:
                break
        self._redraw_placeholders()
        self._load_visible()

    def set_current(self, index):
        if index == self._current_index:
            return
        old = self._current_index
        self._current_index = index
        self._update_highlight(old)
        self._update_highlight(index)
        # scroll to make current visible
        if 0 <= index < len(self._items):
            total_w = len(self._items) * (THUMB_W + THUMB_PAD)
            if total_w > 0:
                frac = (index * (THUMB_W + THUMB_PAD)) / total_w
                self.canvas.xview_moveto(max(0, frac - 0.1))

    def clear(self):
        self._generation += 1
        self._items = []
        self._thumb_cache.clear()
        self._current_index = -1
        self.canvas.delete("all")
        self.canvas.config(scrollregion=(0, 0, 0, 0))

    # -- internal --

    def _redraw_placeholders(self):
        self.canvas.delete("all")
        total_w = len(self._items) * (THUMB_W + THUMB_PAD)
        self.canvas.config(scrollregion=(0, 0, max(total_w, 1), THUMB_H + THUMB_PAD * 2 + 18))

        for i, item in enumerate(self._items):
            x = i * (THUMB_W + THUMB_PAD) + THUMB_PAD // 2
            y = THUMB_PAD
            # Gray placeholder
            self.canvas.create_rectangle(x, y, x + THUMB_W, y + THUMB_H,
                                         fill="#444444", outline="#555555",
                                         tags=(f"bg_{i}",))
            self.canvas.create_text(x + THUMB_W // 2, y + THUMB_H // 2,
                                    text="...", fill="#888888",
                                    tags=(f"placeholder_{i}",))
            # Label below
            label = os.path.basename(item.get("path", ""))
            if len(label) > 10:
                label = label[:9] + ".."
            self.canvas.create_text(x + THUMB_W // 2, y + THUMB_H + 8,
                                    text=label, fill="#aaaaaa",
                                    font=("TkDefaultFont", 7),
                                    tags=(f"label_{i}",))
            # Highlight rect (hidden by default)
            self.canvas.create_rectangle(x - 1, y - 1, x + THUMB_W + 1, y + THUMB_H + 1,
                                         outline="#00aaff", width=2,
                                         state=tk.HIDDEN,
                                         tags=(f"hl_{i}",))

    def _update_highlight(self, index):
        if index < 0 or index >= len(self._items):
            return
        state = tk.NORMAL if index == self._current_index else tk.HIDDEN
        self.canvas.itemconfig(f"hl_{index}", state=state)

    def _on_click(self, event):
        cx = self.canvas.canvasx(event.x)
        idx = int(cx // (THUMB_W + THUMB_PAD))
        if 0 <= idx < len(self._items):
            self.set_current(idx)
            self._on_select(idx)

    def _on_mousewheel(self, event):
        self.canvas.xview_scroll(-1 * (event.delta // 120), "units")
        self.canvas.after(50, self._load_visible)

    def _load_visible(self):
        """Enqueue thumbnail generation for items currently in view."""
        if not self._items:
            return
        # figure out visible range
        try:
            left = self.canvas.canvasx(0)
            right = self.canvas.canvasx(self.canvas.winfo_width())
        except Exception:
            return
        first = max(0, int(left // (THUMB_W + THUMB_PAD)) - 1)
        last = min(len(self._items) - 1, int(right // (THUMB_W + THUMB_PAD)) + 1)

        gen = self._generation
        for i in range(first, last + 1):
            key = (gen, i)
            if key not in self._thumb_cache:
                item = self._items[i]
                self._work_queue.put((gen, i, item))

    def _thumb_worker(self):
        """Background thread that generates thumbnails from the queue."""
        while True:
            try:
                gen, idx, item = self._work_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if gen != self._generation:
                continue  # stale request
            key = (gen, idx)
            if key in self._thumb_cache:
                continue  # already done

            try:
                pil_img = self._generate_thumbnail(item)
                if gen != self._generation:
                    continue
                photo = ImageTk.PhotoImage(pil_img)
                self._thumb_cache[key] = photo
                # schedule canvas update on main thread
                self.canvas.after(0, self._place_thumb, gen, idx, photo)
            except Exception:
                pass  # skip broken files silently

    def _generate_thumbnail(self, item):
        """Return a PIL Image thumbnail for the given item."""
        path = item.get("path", "")
        t = item.get("time")  # optional seek time for video

        if item.get("type") == "video" or _is_video_file(path):
            cap = cv2.VideoCapture(path)
            if t is not None and t > 0:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ret, frame = cap.read()
            cap.release()
            if not ret or frame is None:
                return Image.new("RGB", (THUMB_W, THUMB_H), (68, 68, 68))
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)
        else:
            img = Image.open(path)
            img = img.convert("RGB")

        img.thumbnail((THUMB_W, THUMB_H), Image.NEAREST)
        # Paste onto exact-size canvas to keep uniform sizing
        canvas_img = Image.new("RGB", (THUMB_W, THUMB_H), (43, 43, 43))
        offset_x = (THUMB_W - img.width) // 2
        offset_y = (THUMB_H - img.height) // 2
        canvas_img.paste(img, (offset_x, offset_y))
        return canvas_img

    def _place_thumb(self, gen, idx, photo):
        if gen != self._generation:
            return
        x = idx * (THUMB_W + THUMB_PAD) + THUMB_PAD // 2
        y = THUMB_PAD
        self.canvas.delete(f"placeholder_{idx}")
        self.canvas.create_image(x, y, image=photo, anchor=tk.NW,
                                 tags=(f"thumb_{idx}",))


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
        self.root.geometry("1200x900")

        # Icon
        self.icon_path = _find_icon_path()
        if self.icon_path:
            try:
                self.root.iconbitmap(self.icon_path)
            except tk.TclError:
                pass
        _install_icon_hook(self.root, self.icon_path)

        # Project data
        self.project_file = None
        self.media_files = []       # list of {'path': str, 'type': 'image'|'video'}
        self.selected_indices = []
        self.current_preview_index = 0
        self.current_photo = None   # prevent GC of PhotoImage

        self.output_settings = {
            "format": "mp4",
            "fps": 30,
            "codec": "H264",
            "quality": 80,
        }

        # FFmpeg status
        self.ffmpeg_status = None

        # Playback state
        self._playback_active = False
        self._playback_after_id = None
        self._playback_cap = None           # cv2.VideoCapture during video playback
        self._playback_fps = 30.0
        self._playback_frame_idx = 0
        self._playback_total_frames = 0
        self._playback_duration = 0.0       # seconds
        self._slider_dragging = False

        # Crop-region drawing state
        self._crop_start = None
        self._crop_rect_id = None

        # Build UI
        self.create_menu_bar()
        self.create_layout()

        # Kick off ffmpeg check
        threading.Thread(target=self._check_ffmpeg_async, daemon=True).start()

    # ------------------------------------------------------------------
    # Backward-compat helpers
    # ------------------------------------------------------------------

    @property
    def image_files(self):
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

        # -- File --
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

        # -- Edit --
        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Select All", command=self.select_all)
        edit_menu.add_command(label="Deselect All", command=self.deselect_all)
        edit_menu.add_separator()
        edit_menu.add_command(label="Delete Selected", command=self.delete_selected)
        edit_menu.add_separator()
        edit_menu.add_command(label="Move Up", command=lambda: self.move_selected(-1))
        edit_menu.add_command(label="Move Down", command=lambda: self.move_selected(1))
        menubar.add_cascade(label="Edit", menu=edit_menu)

        # -- Preview --
        preview_menu = tk.Menu(menubar, tearoff=0)
        preview_menu.add_command(label="Preview Current Frame", command=self.preview_current)
        preview_menu.add_command(label="Create Preview Video", command=self.create_preview)
        menubar.add_cascade(label="Preview", menu=preview_menu)

        # -- Video (image->video) --
        video_create_menu = tk.Menu(menubar, tearoff=0)
        video_create_menu.add_command(label="Output Settings", command=self.show_output_settings)
        video_create_menu.add_separator()
        video_create_menu.add_command(label="Create Video", command=self.create_video)
        menubar.add_cascade(label="Video", menu=video_create_menu)

        # -- Video Ops (ffmpeg) --
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

        # -- Filters --
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

        # -- Metadata --
        meta_menu = tk.Menu(menubar, tearoff=0)
        meta_menu.add_command(label="View Metadata", command=self.view_metadata)
        meta_menu.add_command(label="Edit Metadata", command=self.edit_metadata)
        meta_menu.add_separator()
        meta_menu.add_command(label="Strip Metadata (Fast)", command=self.strip_metadata)
        meta_menu.add_command(label="Strip Metadata (Deep - re-encode)",
                              command=self.strip_metadata_deep)
        menubar.add_cascade(label="Metadata", menu=meta_menu)

        # -- Tools --
        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="Batch Process", command=self.batch_process)
        tools_menu.add_command(label="Export File List", command=self.export_file_list)
        tools_menu.add_command(label="Import File List", command=self.import_file_list)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        # -- Help --
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
    # Layout  (preview top, media list bottom)
    # ------------------------------------------------------------------

    def create_layout(self):
        # Main container using grid for weight control
        main = ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        main.rowconfigure(0, weight=3)   # preview
        main.rowconfigure(1, weight=0)   # transport controls
        main.rowconfigure(2, weight=0)   # thumbnail strip
        main.rowconfigure(3, weight=1)   # bottom panel (list + props)
        main.columnconfigure(0, weight=1)

        # ---- ROW 0: Preview canvas ----
        preview_frame = ttk.Frame(main, relief=tk.SUNKEN, borderwidth=1)
        preview_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 4))
        preview_frame.rowconfigure(0, weight=1)
        preview_frame.columnconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(preview_frame, bg="black",
                                        highlightthickness=0)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")

        # Bind for crop-region drawing
        self.preview_canvas.bind("<ButtonPress-1>", self._crop_mouse_down)
        self.preview_canvas.bind("<B1-Motion>", self._crop_mouse_drag)
        self.preview_canvas.bind("<ButtonRelease-1>", self._crop_mouse_up)

        # ---- ROW 1: Transport controls ----
        transport = ttk.Frame(main)
        transport.grid(row=1, column=0, sticky="ew", pady=2)
        transport.columnconfigure(1, weight=1)  # slider stretches

        # Row 1a: buttons + time + slider
        btn_row = ttk.Frame(transport)
        btn_row.pack(fill=tk.X)

        ttk.Button(btn_row, text="<<", width=3,
                   command=self._transport_first).pack(side=tk.LEFT, padx=1)
        ttk.Button(btn_row, text="<", width=3,
                   command=self._transport_prev).pack(side=tk.LEFT, padx=1)
        self._play_btn = ttk.Button(btn_row, text="Play", width=6,
                                    command=self._transport_play_pause)
        self._play_btn.pack(side=tk.LEFT, padx=1)
        ttk.Button(btn_row, text="Stop", width=4,
                   command=self._transport_stop).pack(side=tk.LEFT, padx=1)
        ttk.Button(btn_row, text=">", width=3,
                   command=self._transport_next).pack(side=tk.LEFT, padx=1)
        ttk.Button(btn_row, text=">>", width=3,
                   command=self._transport_last).pack(side=tk.LEFT, padx=1)

        self._time_label = ttk.Label(btn_row, text="0:00 / 0:00", width=16)
        self._time_label.pack(side=tk.LEFT, padx=8)

        # Action buttons on right side of transport
        ttk.Button(btn_row, text="Mute Section",
                   command=self._mute_section).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_row, text="Trim Section",
                   command=self._trim_section).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_row, text="Crop Region",
                   command=self._start_crop_region).pack(side=tk.RIGHT, padx=2)

        # Slider row
        slider_row = ttk.Frame(transport)
        slider_row.pack(fill=tk.X, pady=(2, 0))

        self._position_var = tk.DoubleVar(value=0)
        self._position_slider = ttk.Scale(slider_row, from_=0, to=100,
                                          orient=tk.HORIZONTAL,
                                          variable=self._position_var,
                                          command=self._on_slider_move)
        self._position_slider.pack(fill=tk.X, padx=4)
        self._position_slider.bind("<ButtonPress-1>", self._slider_press)
        self._position_slider.bind("<ButtonRelease-1>", self._slider_release)

        # ---- ROW 2: Thumbnail strip ----
        self.thumb_strip = ThumbnailStrip(main, on_select_callback=self._on_thumb_select)
        self.thumb_strip.frame.grid(row=2, column=0, sticky="ew", pady=4)

        # ---- ROW 3: Bottom panel (file list + properties) ----
        bottom = ttk.PanedWindow(main, orient=tk.HORIZONTAL)
        bottom.grid(row=3, column=0, sticky="nsew", pady=(4, 0))

        # -- Left: media file list --
        list_frame = ttk.Frame(bottom)
        bottom.add(list_frame, weight=2)

        ttk.Label(list_frame, text="Media Files").pack(anchor=tk.W, pady=(0, 3))

        lb_frame = ttk.Frame(list_frame)
        lb_frame.pack(fill=tk.BOTH, expand=True)

        self.file_listbox = tk.Listbox(lb_frame, selectmode=tk.EXTENDED)
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.file_listbox.bind("<<ListboxSelect>>", self.on_file_select)

        lb_scroll = ttk.Scrollbar(lb_frame, orient=tk.VERTICAL,
                                  command=self.file_listbox.yview)
        lb_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_listbox.config(yscrollcommand=lb_scroll.set)

        btn_bar = ttk.Frame(list_frame)
        btn_bar.pack(fill=tk.X, pady=4)

        ttk.Button(btn_bar, text="Add Files",
                   command=self.import_images).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_bar, text="Add Videos",
                   command=self.import_videos).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_bar, text="Remove",
                   command=self.delete_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_bar, text="Up", width=3,
                   command=lambda: self.move_selected(-1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_bar, text="Down", width=3,
                   command=lambda: self.move_selected(1)).pack(side=tk.LEFT, padx=2)

        # -- Right: properties --
        props_frame = ttk.Frame(bottom)
        bottom.add(props_frame, weight=1)

        props_lf = ttk.LabelFrame(props_frame, text="Output Properties")
        props_lf.pack(fill=tk.X, padx=(4, 0), pady=(0, 4))

        fps_f = ttk.Frame(props_lf)
        fps_f.pack(fill=tk.X, padx=5, pady=3)
        ttk.Label(fps_f, text="FPS:").pack(side=tk.LEFT)
        self.fps_var = tk.StringVar(value=str(self.output_settings["fps"]))
        fps_sb = ttk.Spinbox(fps_f, from_=1, to=120,
                             textvariable=self.fps_var, width=5)
        fps_sb.pack(side=tk.LEFT, padx=5)
        fps_sb.bind("<<SpinboxSelected>>", self.update_fps)

        fmt_f = ttk.Frame(props_lf)
        fmt_f.pack(fill=tk.X, padx=5, pady=3)
        ttk.Label(fmt_f, text="Format:").pack(side=tk.LEFT)
        self.format_var = tk.StringVar(value=self.output_settings["format"])
        fmt_cb = ttk.Combobox(fmt_f, textvariable=self.format_var,
                              values=["mp4", "avi", "mov", "webm"], width=5)
        fmt_cb.pack(side=tk.LEFT, padx=5)
        fmt_cb.bind("<<ComboboxSelected>>", self.update_format)

        codec_f = ttk.Frame(props_lf)
        codec_f.pack(fill=tk.X, padx=5, pady=3)
        ttk.Label(codec_f, text="Codec:").pack(side=tk.LEFT)
        self.codec_var = tk.StringVar(value=self.output_settings["codec"])
        codec_cb = ttk.Combobox(codec_f, textvariable=self.codec_var,
                                values=["H264", "MJPG", "XVID", "VP9"], width=5)
        codec_cb.pack(side=tk.LEFT, padx=5)
        codec_cb.bind("<<ComboboxSelected>>", self.update_codec)

        # Video info label
        self.video_info_label = ttk.Label(props_frame, text="", wraplength=350,
                                          foreground="gray")
        self.video_info_label.pack(fill=tk.X, padx=(4, 0), pady=4)

        ttk.Button(props_frame, text="Create Video",
                   command=self.create_video).pack(anchor=tk.E, padx=(4, 0), pady=4)

        # ---- Status bar ----
        self.status_var = tk.StringVar(value="Starting up...")
        status_bar = ttk.Label(self.root, textvariable=self.status_var,
                               relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    # ------------------------------------------------------------------
    # Thumbnail strip callbacks
    # ------------------------------------------------------------------

    def _on_thumb_select(self, index):
        """Called when the user clicks a thumbnail in the strip."""
        if self._is_single_video_mode():
            # index = frame/time index within the video
            self._seek_video_to_thumb(index)
        else:
            if 0 <= index < len(self.media_files):
                self.current_preview_index = index
                self.file_listbox.selection_clear(0, tk.END)
                self.file_listbox.selection_set(index)
                self.file_listbox.see(index)
                self.update_preview()

    def _rebuild_thumb_strip(self):
        """Rebuild the thumbnail strip based on current state."""
        if self._is_single_video_mode():
            path = self.media_files[self.current_preview_index]["path"]
            self._build_video_thumbs(path)
        else:
            items = [{"path": m["path"], "type": m["type"]}
                     for m in self.media_files]
            self.thumb_strip.set_items(items)
            self.thumb_strip.set_current(self.current_preview_index)

    def _build_video_thumbs(self, video_path):
        """Build thumbnail strip items for a single video at time intervals."""
        try:
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            cap.release()
            duration = total / fps if fps > 0 else 0
        except Exception:
            duration = 0

        if duration <= 0:
            self.thumb_strip.clear()
            return

        # At most 50 thumbnails, spaced evenly
        n_thumbs = min(50, max(10, int(duration / 2)))
        interval = duration / n_thumbs
        items = []
        for i in range(n_thumbs):
            t = i * interval
            items.append({"path": video_path, "type": "video", "time": t})
        self.thumb_strip.set_items(items)

    def _seek_video_to_thumb(self, thumb_index):
        """Seek the video preview to the time represented by thumb_index."""
        items = self.thumb_strip._items
        if thumb_index < 0 or thumb_index >= len(items):
            return
        t = items[thumb_index].get("time", 0)
        path = items[thumb_index]["path"]

        try:
            cap = cv2.VideoCapture(path)
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ret, frame = cap.read()
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            cap.release()
            if ret and frame is not None:
                self._display_cv2_frame(frame)
                duration = total_frames / fps if fps > 0 else 0
                self._time_label.config(
                    text=f"{_format_time_short(t)} / {_format_time_short(duration)}")
                if duration > 0:
                    self._position_var.set(t / duration * 100)
        except Exception:
            pass
        self.thumb_strip.set_current(thumb_index)

    def _is_single_video_mode(self):
        """True if exactly one video is selected/current in the list."""
        if not self.media_files:
            return False
        if len(self.media_files) == 1 and self.media_files[0]["type"] == "video":
            return True
        if (self.selected_indices and len(self.selected_indices) == 1):
            idx = self.selected_indices[0]
            if idx < len(self.media_files) and self.media_files[idx]["type"] == "video":
                return True
        return False

    # ------------------------------------------------------------------
    # Transport controls (play/pause/stop/seek)
    # ------------------------------------------------------------------

    def _transport_play_pause(self):
        if self._playback_active:
            self._pause_playback()
        else:
            self._start_playback()

    def _transport_stop(self):
        self._stop_playback()

    def _transport_first(self):
        self._stop_playback()
        if self._is_single_video_mode():
            self._seek_video_frame(0)
        else:
            self.current_preview_index = 0
            self.update_preview()
            self.thumb_strip.set_current(0)

    def _transport_last(self):
        self._stop_playback()
        if self._is_single_video_mode():
            if self._playback_total_frames > 0:
                self._seek_video_frame(self._playback_total_frames - 1)
        else:
            if self.media_files:
                self.current_preview_index = len(self.media_files) - 1
                self.update_preview()
                self.thumb_strip.set_current(self.current_preview_index)

    def _transport_prev(self):
        if self._playback_active:
            self._pause_playback()
        if self._is_single_video_mode():
            new_idx = max(0, self._playback_frame_idx - 1)
            self._seek_video_frame(new_idx)
        else:
            self.current_preview_index = max(0, self.current_preview_index - 1)
            self.update_preview()
            self.thumb_strip.set_current(self.current_preview_index)

    def _transport_next(self):
        if self._playback_active:
            self._pause_playback()
        if self._is_single_video_mode():
            new_idx = min(self._playback_total_frames - 1,
                          self._playback_frame_idx + 1)
            self._seek_video_frame(new_idx)
        else:
            if self.media_files:
                self.current_preview_index = min(len(self.media_files) - 1,
                                                 self.current_preview_index + 1)
                self.update_preview()
                self.thumb_strip.set_current(self.current_preview_index)

    def _start_playback(self):
        if not self.media_files:
            return

        if self._is_single_video_mode():
            idx = self.selected_indices[0] if self.selected_indices else 0
            path = self.media_files[idx]["path"]
            self._start_video_playback(path)
        else:
            self._start_image_playback()

    def _start_image_playback(self):
        """Play through images in the media list as a slideshow."""
        images = self.image_files
        if len(images) < 2:
            return
        try:
            fps = int(self.fps_var.get())
        except ValueError:
            fps = 30
        self._playback_fps = fps
        self._playback_active = True
        self._play_btn.config(text="Pause")
        self._playback_total_frames = len(self.media_files)
        self._playback_duration = self._playback_total_frames / fps
        self._image_playback_tick()

    def _image_playback_tick(self):
        if not self._playback_active:
            return
        if self.current_preview_index >= len(self.media_files) - 1:
            self._stop_playback()
            return

        self.current_preview_index += 1
        self.update_preview()
        self.thumb_strip.set_current(self.current_preview_index)
        self._update_transport_display_images()

        interval = max(1, int(1000 / self._playback_fps))
        self._playback_after_id = self.root.after(interval,
                                                  self._image_playback_tick)

    def _update_transport_display_images(self):
        idx = self.current_preview_index
        total = len(self.media_files)
        cur_t = idx / self._playback_fps if self._playback_fps > 0 else 0
        tot_t = total / self._playback_fps if self._playback_fps > 0 else 0
        self._time_label.config(
            text=f"{_format_time_short(cur_t)} / {_format_time_short(tot_t)}")
        if total > 1:
            self._position_var.set(idx / (total - 1) * 100)

    def _start_video_playback(self, path):
        """Start playing a video file frame by frame."""
        if self._playback_cap is not None:
            self._playback_cap.release()

        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            messagebox.showerror("Error", f"Cannot open video: {path}")
            return

        self._playback_cap = cap
        self._playback_fps = cap.get(cv2.CAP_PROP_FPS) or 30
        self._playback_total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self._playback_duration = (self._playback_total_frames / self._playback_fps
                                   if self._playback_fps > 0 else 0)

        # Seek to current position if resuming
        if self._playback_frame_idx > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, self._playback_frame_idx)

        self._playback_active = True
        self._play_btn.config(text="Pause")
        self._position_slider.config(to=100)
        self._video_playback_tick()

    def _video_playback_tick(self):
        if not self._playback_active or self._playback_cap is None:
            return

        ret, frame = self._playback_cap.read()
        if not ret:
            self._stop_playback()
            return

        self._playback_frame_idx = int(
            self._playback_cap.get(cv2.CAP_PROP_POS_FRAMES))

        self._display_cv2_frame(frame)
        self._update_transport_display_video()

        interval = max(1, int(1000 / self._playback_fps))
        self._playback_after_id = self.root.after(interval,
                                                  self._video_playback_tick)

    def _update_transport_display_video(self):
        if self._playback_fps <= 0:
            return
        cur_t = self._playback_frame_idx / self._playback_fps
        self._time_label.config(
            text=f"{_format_time_short(cur_t)} / "
                 f"{_format_time_short(self._playback_duration)}")
        if not self._slider_dragging and self._playback_duration > 0:
            pct = cur_t / self._playback_duration * 100
            self._position_var.set(pct)

    def _pause_playback(self):
        self._playback_active = False
        self._play_btn.config(text="Play")
        if self._playback_after_id:
            self.root.after_cancel(self._playback_after_id)
            self._playback_after_id = None

    def _stop_playback(self):
        self._pause_playback()
        self._playback_frame_idx = 0
        if self._playback_cap is not None:
            self._playback_cap.release()
            self._playback_cap = None
        self._position_var.set(0)
        self._time_label.config(
            text=f"0:00 / {_format_time_short(self._playback_duration)}")
        self._play_btn.config(text="Play")

    def _seek_video_frame(self, frame_idx):
        """Seek to a specific frame in single-video mode and display it."""
        if not self._is_single_video_mode():
            return
        idx = self.selected_indices[0] if self.selected_indices else 0
        path = self.media_files[idx]["path"]

        try:
            cap = self._playback_cap
            if cap is None or not cap.isOpened():
                cap = cv2.VideoCapture(path)
                self._playback_cap = cap
                self._playback_fps = cap.get(cv2.CAP_PROP_FPS) or 30
                self._playback_total_frames = int(
                    cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                self._playback_duration = (
                    self._playback_total_frames / self._playback_fps
                    if self._playback_fps > 0 else 0)

            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if ret and frame is not None:
                self._playback_frame_idx = frame_idx
                self._display_cv2_frame(frame)
                self._update_transport_display_video()
        except Exception:
            pass

    # -- Slider interaction --

    def _slider_press(self, event):
        self._slider_dragging = True

    def _slider_release(self, event):
        self._slider_dragging = False
        self._on_slider_seek()

    def _on_slider_move(self, value):
        """Called as the slider is dragged (live feedback)."""
        if not self._slider_dragging:
            return
        # Show time label update while dragging
        pct = float(value)
        if self._is_single_video_mode() and self._playback_duration > 0:
            t = pct / 100 * self._playback_duration
            self._time_label.config(
                text=f"{_format_time_short(t)} / "
                     f"{_format_time_short(self._playback_duration)}")

    def _on_slider_seek(self):
        """Seek to the position indicated by the slider."""
        pct = self._position_var.get()
        if self._is_single_video_mode():
            if self._playback_duration > 0 and self._playback_fps > 0:
                t = pct / 100 * self._playback_duration
                frame_idx = int(t * self._playback_fps)
                frame_idx = max(0, min(frame_idx,
                                       self._playback_total_frames - 1))
                self._seek_video_frame(frame_idx)
        else:
            if self.media_files:
                idx = int(pct / 100 * (len(self.media_files) - 1))
                idx = max(0, min(idx, len(self.media_files) - 1))
                self.current_preview_index = idx
                self.update_preview()
                self.thumb_strip.set_current(idx)

    # ------------------------------------------------------------------
    # Section editing tools (transport bar)
    # ------------------------------------------------------------------

    def _mute_section(self):
        """Mute audio in a time range of the selected video."""
        if not self._require_ffmpeg():
            return
        path = self._get_selected_video_path()
        if not path:
            messagebox.showinfo("Mute Section",
                                "Select a video file in the list first.")
            return

        try:
            info = video_ops.get_video_info(path)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read video: {e}")
            return

        dlg = TrimDialog(self.root, info["duration"])
        self.root.wait_window(dlg)
        if dlg.result is None:
            return

        start_t, end_t = dlg.result
        base, ext = os.path.splitext(path)
        default_name = f"{os.path.basename(base)}_muted_section{ext}"

        output_file = filedialog.asksaveasfilename(
            title="Save Video With Muted Section",
            initialfile=default_name,
            defaultextension=ext,
            filetypes=[("Video files", f"*{ext}"), ("All files", "*.*")],
        )
        if not output_file:
            return

        def op(cb):
            from .ffmpeg_utils import run_ffmpeg
            args = [
                "-i", path,
                "-af",
                f"volume=enable='between(t,{start_t},{end_t})':volume=0",
                "-c:v", "copy",
                "-y", output_file,
            ]
            run_ffmpeg(args, progress_callback=cb)
            return f"Audio muted from {_format_time_short(start_t)} to " \
                   f"{_format_time_short(end_t)}.\nSaved to:\n{output_file}"

        self._run_video_op("Muting Section", op)

    def _trim_section(self):
        """Trim the selected video - opens trim dialog with convenience."""
        self.trim_video()

    def _start_crop_region(self):
        """Enable crop-region drawing mode on the preview canvas."""
        if not self.media_files:
            messagebox.showinfo("Crop Region", "No media loaded.")
            return
        self._crop_mode = True
        self._crop_start = None
        self.status_var.set("Crop mode: click and drag on the preview to select a region")
        self.preview_canvas.config(cursor="crosshair")

    _crop_mode = False

    def _crop_mouse_down(self, event):
        if not self._crop_mode:
            return
        self._crop_start = (event.x, event.y)
        if self._crop_rect_id:
            self.preview_canvas.delete(self._crop_rect_id)
        self._crop_rect_id = self.preview_canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="#00ff00", width=2, dash=(4, 4))

    def _crop_mouse_drag(self, event):
        if not self._crop_mode or self._crop_start is None:
            return
        x0, y0 = self._crop_start
        self.preview_canvas.coords(self._crop_rect_id, x0, y0, event.x, event.y)

    def _crop_mouse_up(self, event):
        if not self._crop_mode or self._crop_start is None:
            return
        self._crop_mode = False
        self.preview_canvas.config(cursor="")

        x0, y0 = self._crop_start
        x1, y1 = event.x, event.y
        self._crop_start = None

        # Normalize
        left, right = min(x0, x1), max(x0, x1)
        top, bottom = min(y0, y1), max(y0, y1)

        if right - left < 5 or bottom - top < 5:
            if self._crop_rect_id:
                self.preview_canvas.delete(self._crop_rect_id)
            self.status_var.set("Crop cancelled - region too small")
            return

        # Convert canvas coords to image coords
        canvas_w = self.preview_canvas.winfo_width()
        canvas_h = self.preview_canvas.winfo_height()

        # Get current media dimensions
        entry = self.media_files[self.current_preview_index]
        try:
            if entry["type"] == "video":
                cap = cv2.VideoCapture(entry["path"])
                img_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                img_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cap.release()
            else:
                img = Image.open(entry["path"])
                img_w, img_h = img.size
        except Exception:
            self.status_var.set("Could not determine image dimensions")
            return

        scale = min(canvas_w / img_w, canvas_h / img_h)
        disp_w = int(img_w * scale)
        disp_h = int(img_h * scale)
        offset_x = (canvas_w - disp_w) // 2
        offset_y = (canvas_h - disp_h) // 2

        # Map canvas coords to image coords
        crop_left = int((left - offset_x) / scale)
        crop_top = int((top - offset_y) / scale)
        crop_right = int((right - offset_x) / scale)
        crop_bottom = int((bottom - offset_y) / scale)

        # Clamp
        crop_left = max(0, min(crop_left, img_w))
        crop_top = max(0, min(crop_top, img_h))
        crop_right = max(0, min(crop_right, img_w))
        crop_bottom = max(0, min(crop_bottom, img_h))

        if self._crop_rect_id:
            self.preview_canvas.delete(self._crop_rect_id)

        if crop_right - crop_left < 2 or crop_bottom - crop_top < 2:
            self.status_var.set("Crop cancelled - region outside image")
            return

        result = messagebox.askyesnocancel(
            "Apply Crop",
            f"Crop region: ({crop_left}, {crop_top}) to ({crop_right}, {crop_bottom})\n"
            f"Size: {crop_right - crop_left} x {crop_bottom - crop_top}\n\n"
            "Yes = Apply to all selected images\n"
            "No = Apply to current image only\n"
            "Cancel = Discard",
        )
        if result is None:
            self.status_var.set("Crop cancelled")
            return

        if entry["type"] == "video":
            # For video, use ffmpeg crop filter
            if not self._require_ffmpeg():
                return
            w = crop_right - crop_left
            h = crop_bottom - crop_top
            base, ext = os.path.splitext(entry["path"])
            out = filedialog.asksaveasfilename(
                title="Save Cropped Video",
                initialfile=f"{os.path.basename(base)}_cropped{ext}",
                defaultextension=ext)
            if not out:
                return

            def op(cb):
                from .ffmpeg_utils import run_ffmpeg
                args = [
                    "-i", entry["path"],
                    "-vf", f"crop={w}:{h}:{crop_left}:{crop_top}",
                    "-c:a", "copy",
                    "-y", out,
                ]
                run_ffmpeg(args, progress_callback=cb)
                return f"Cropped video saved to:\n{out}"
            self._run_video_op("Cropping Video", op)
        else:
            # Image crop
            cl, ct, cr, cb = crop_left, crop_top, crop_right, crop_bottom

            def _do_crop(img):
                return img[ct:cb, cl:cr]

            if result:  # Yes = all selected
                self._apply_cv2_filter_to_selected(_do_crop, "Crop")
            else:  # No = current only
                p = entry["path"]
                img = cv2.imread(p)
                if img is not None:
                    cv2.imwrite(p, _do_crop(img))
                    self.update_preview()
                    self.status_var.set("Crop applied to current image")

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def _display_cv2_frame(self, frame):
        """Display an OpenCV BGR frame on the preview canvas."""
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(frame_rgb)

        canvas_w = self.preview_canvas.winfo_width()
        canvas_h = self.preview_canvas.winfo_height()
        if canvas_w <= 1 or canvas_h <= 1:
            return

        img_w, img_h = img.size
        scale = min(canvas_w / img_w, canvas_h / img_h)
        new_w = int(img_w * scale)
        new_h = int(img_h * scale)

        img_resized = img.resize((new_w, new_h), Image.BILINEAR)
        photo = ImageTk.PhotoImage(img_resized)
        self.current_photo = photo

        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(
            canvas_w // 2, canvas_h // 2,
            image=photo, anchor=tk.CENTER)

    # ------------------------------------------------------------------
    # Listbox helpers
    # ------------------------------------------------------------------

    def _refresh_listbox(self):
        self.file_listbox.delete(0, tk.END)
        for entry in self.media_files:
            self.file_listbox.insert(tk.END, _listbox_display(entry))

    def _get_selected_video_path(self):
        indices = list(self.file_listbox.curselection())
        for idx in indices:
            if idx < len(self.media_files) and self.media_files[idx]["type"] == "video":
                return self.media_files[idx]["path"]
        return None

    def _get_selected_video_paths(self):
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
        self._stop_playback()
        self.project_file = None
        self.media_files = []
        self.selected_indices = []
        self.current_preview_index = 0
        self.file_listbox.delete(0, tk.END)
        self.update_preview()
        self.thumb_strip.clear()
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
            raw_files = project_data.get("media_files") or project_data.get("image_files", [])
            self.media_files = []
            for item in raw_files:
                if isinstance(item, str):
                    mtype = "video" if _is_video_file(item) else "image"
                    self.media_files.append({"path": item, "type": mtype})
                elif isinstance(item, dict):
                    self.media_files.append(item)

            self.output_settings = project_data.get("output_settings", self.output_settings)
            self._refresh_listbox()
            self.fps_var.set(str(self.output_settings["fps"]))
            self.format_var.set(self.output_settings["format"])
            self.codec_var.set(self.output_settings["codec"])
            self.current_preview_index = 0
            self.update_preview()
            self._rebuild_thumb_strip()
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
        self._rebuild_thumb_strip()

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
            messagebox.showinfo("No files found",
                                f"No files matching '{pattern}' in that directory.")
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
        self._rebuild_thumb_strip()

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
        self._rebuild_thumb_strip()

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
        self._rebuild_thumb_strip()

    def move_selected(self, direction):
        if not self.selected_indices or len(self.selected_indices) != 1:
            return
        idx = self.selected_indices[0]
        target_idx = idx + direction
        if target_idx < 0 or target_idx >= len(self.media_files):
            return
        self.media_files[idx], self.media_files[target_idx] = (
            self.media_files[target_idx], self.media_files[idx])
        self.file_listbox.delete(idx)
        self.file_listbox.insert(target_idx,
                                 _listbox_display(self.media_files[target_idx]))
        self.file_listbox.selection_clear(0, tk.END)
        self.file_listbox.selection_set(target_idx)
        self.selected_indices = [target_idx]
        if idx == self.current_preview_index:
            self.current_preview_index = target_idx
            self.update_preview()
        self._rebuild_thumb_strip()

    # ------------------------------------------------------------------
    # Selection and preview
    # ------------------------------------------------------------------

    def on_file_select(self, event):
        self.update_selected_indices()
        if len(self.selected_indices) == 1:
            self.current_preview_index = self.selected_indices[0]
            self._stop_playback()
            self.update_preview()
            self._show_selected_info()
            self._rebuild_thumb_strip()

    def _show_selected_info(self):
        if not self.selected_indices:
            self.video_info_label.config(text="")
            return
        idx = self.selected_indices[0]
        if idx >= len(self.media_files):
            return
        entry = self.media_files[idx]
        if entry["type"] == "video":
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
            self._time_label.config(text="0:00 / 0:00")
            return
        if self.current_preview_index >= len(self.media_files):
            self.current_preview_index = len(self.media_files) - 1

        entry = self.media_files[self.current_preview_index]
        path = entry["path"]

        if entry["type"] == "video":
            self._preview_video_thumbnail(path)
        else:
            self._preview_image(path)

        self._update_transport_display_images()

    def _preview_image(self, image_path):
        try:
            img = Image.open(image_path)
            canvas_w = self.preview_canvas.winfo_width()
            canvas_h = self.preview_canvas.winfo_height()
            if canvas_w <= 1 or canvas_h <= 1:
                self.preview_canvas.after(100, self.update_preview)
                return
            img_w, img_h = img.size
            scale = min(canvas_w / img_w, canvas_h / img_h)
            new_w = int(img_w * scale)
            new_h = int(img_h * scale)
            img_resized = img.resize((new_w, new_h), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img_resized)
            self.current_photo = photo
            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(
                canvas_w // 2, canvas_h // 2,
                image=photo, anchor=tk.CENTER)
            self.status_var.set(
                f"{os.path.basename(image_path)} - {img_w}x{img_h}")
        except Exception as e:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                self.preview_canvas.winfo_width() // 2,
                self.preview_canvas.winfo_height() // 2,
                text=f"Error loading image: {e}", fill="white")

    def _preview_video_thumbnail(self, video_path):
        try:
            cap = cv2.VideoCapture(video_path)
            ret, frame = cap.read()
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            cap.release()
            if not ret or frame is None:
                raise RuntimeError("Could not read first frame")

            self._playback_fps = fps
            self._playback_total_frames = total
            self._playback_duration = total / fps if fps > 0 else 0

            self._display_cv2_frame(frame)

            w = frame.shape[1]
            h = frame.shape[0]
            self.status_var.set(
                f"[VIDEO] {os.path.basename(video_path)} - {w}x{h}")
            self._time_label.config(
                text=f"0:00 / {_format_time_short(self._playback_duration)}")
        except Exception as e:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                self.preview_canvas.winfo_width() // 2,
                self.preview_canvas.winfo_height() // 2,
                text=f"Error: {e}", fill="white")

    # ------------------------------------------------------------------
    # Custom dialog helpers
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

        fps_dialog = tk.Toplevel(self.root)
        fps_dialog.title("Preview FPS")
        fps_dialog.geometry("300x120")
        fps_dialog.transient(self.root)
        fps_dialog.grab_set()
        fps_dialog.resizable(False, False)

        frame = ttk.Frame(fps_dialog, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Enter frames per second for preview:").pack(
            anchor=tk.W, pady=(0, 10))
        fps_var = tk.IntVar(value=self.output_settings["fps"])
        fps_spinbox = ttk.Spinbox(frame, from_=1, to=60,
                                  textvariable=fps_var, width=10)
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
                    messagebox.showwarning("Invalid", "Value must be 1-60.")
            except ValueError:
                messagebox.showwarning("Invalid", "Enter a valid number.")

        ttk.Button(button_frame, text="OK", command=on_ok).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel",
                   command=fps_dialog.destroy).pack(side=tk.RIGHT, padx=5)
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
        progress = ProgressDialog(self.root, "Creating Preview",
                                  maximum=len(preview_files))

        def _thread():
            try:
                first_img = cv2.imread(preview_files[0])
                if first_img is None:
                    raise RuntimeError(f"Cannot read: {preview_files[0]}")
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
                self.root.after(0, messagebox.showerror, "Error",
                                f"Failed to create preview: {e}")

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
        ttk.Spinbox(frame, from_=1, to=120, textvariable=fps_var, width=10).grid(
            row=0, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Output Format:").grid(row=1, column=0, sticky=tk.W, pady=5)
        format_var = tk.StringVar(value=self.output_settings["format"])
        ttk.Combobox(frame, textvariable=format_var,
                     values=["mp4", "avi", "mov", "webm"], width=10).grid(
            row=1, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Video Codec:").grid(row=2, column=0, sticky=tk.W, pady=5)
        codec_var = tk.StringVar(value=self.output_settings["codec"])
        ttk.Combobox(frame, textvariable=codec_var,
                     values=["H264", "MJPG", "XVID", "VP9"], width=10).grid(
            row=2, column=1, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Quality (0-100):").grid(row=3, column=0, sticky=tk.W, pady=5)
        quality_var = tk.StringVar(value=str(self.output_settings["quality"]))
        ttk.Spinbox(frame, from_=0, to=100, textvariable=quality_var, width=10).grid(
            row=3, column=1, sticky=tk.W, pady=5)

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
        ttk.Button(button_frame, text="Cancel",
                   command=settings.destroy).pack(side=tk.LEFT, padx=5)

    # ------------------------------------------------------------------
    # Create video from images
    # ------------------------------------------------------------------

    def create_video(self):
        images = self.image_files
        if len(images) < 2:
            messagebox.showinfo("Create Video", "Need at least 2 images.")
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
                    raise RuntimeError(f"Cannot read: {images[0]}")
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

                out = cv2.VideoWriter(output_file, fourcc,
                                      self.output_settings["fps"], (width, height))
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
                    f"Video created at:\n{output_file}\n\nPlay it now?")
                if play:
                    self.play_output_file(output_file)
            except Exception as e:
                self.root.after(0, progress.destroy)
                self.root.after(0, messagebox.showerror, "Error",
                                f"Failed to create video: {e}")

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
        progress = ProgressDialog(self.root, title, maximum=100)

        def _cb(pct):
            self.root.after(0, progress.update_progress, pct, f"{pct:.0f}%")

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

    # -- Merge Videos --

    def merge_videos(self):
        if not self._require_ffmpeg():
            return
        paths = self._get_selected_video_paths()
        if len(paths) < 2:
            messagebox.showinfo("Merge Videos",
                                "Select at least 2 video files to merge.")
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

    # -- Split Video --

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

        output_dir = filedialog.askdirectory(title="Select Output Directory")
        if not output_dir:
            return
        split_points = dlg.result

        def op(cb):
            result_files = video_ops.split_video(path, output_dir, split_points,
                                                 progress_callback=cb)
            return f"Split into {len(result_files)} segment(s) in:\n{output_dir}"
        self._run_video_op("Splitting Video", op)

    # -- Trim Video --

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
            initialfile=default_name, defaultextension=ext,
            filetypes=[("Video files", f"*{ext}"), ("All files", "*.*")],
        )
        if not output_file:
            return

        def op(cb):
            video_ops.trim_video(path, output_file, start_time, end_time,
                                 progress_callback=cb)
            return f"Trimmed video saved to:\n{output_file}"
        self._run_video_op("Trimming Video", op)

    # -- Mute Audio --

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
            initialfile=default_name, defaultextension=ext,
            filetypes=[("Video files", f"*{ext}"), ("All files", "*.*")],
        )
        if not output_file:
            return

        def op(cb):
            video_ops.mute_audio(path, output_file, progress_callback=cb)
            return f"Audio removed. Saved to:\n{output_file}"
        self._run_video_op("Removing Audio", op)

    # -- Extract Audio --

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
            initialfile=f"{base}_audio.aac", defaultextension=".aac",
            filetypes=[("AAC", "*.aac"), ("MP3", "*.mp3"),
                       ("WAV", "*.wav"), ("All files", "*.*")],
        )
        if not output_file:
            return

        def op(cb):
            video_ops.extract_audio(path, output_file, progress_callback=cb)
            return f"Audio extracted to:\n{output_file}"
        self._run_video_op("Extracting Audio", op)

    # -- Add Audio --

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
            "Yes = replace original audio\nNo = add as additional stream")
        base, ext = os.path.splitext(path)
        default_name = f"{os.path.basename(base)}_with_audio{ext}"
        output_file = filedialog.asksaveasfilename(
            title="Save Video With Audio As",
            initialfile=default_name, defaultextension=ext,
            filetypes=[("Video files", f"*{ext}"), ("All files", "*.*")],
        )
        if not output_file:
            return

        def op(cb):
            video_ops.add_audio(path, audio_file, output_file,
                                replace=replace, progress_callback=cb)
            return f"Audio added. Saved to:\n{output_file}"
        self._run_video_op("Adding Audio", op)

    # -- Change Speed --

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
            initialfile=default_name, defaultextension=ext,
            filetypes=[("Video files", f"*{ext}"), ("All files", "*.*")],
        )
        if not output_file:
            return

        def op(cb):
            video_ops.change_speed(path, output_file, speed_factor,
                                   progress_callback=cb)
            return f"Speed changed ({speed_factor}x). Saved to:\n{output_file}"
        self._run_video_op("Changing Speed", op)

    # -- Extract Frames --

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
        output_dir = filedialog.askdirectory(title="Select Output Directory")
        if not output_dir:
            return

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
                progress_callback=cb)
            self.root.after(0, self._offer_add_extracted_frames, result_files)
            return f"Extracted {len(result_files)} frame(s) to:\n{output_dir}"
        self._run_video_op("Extracting Frames", op)

    def _offer_add_extracted_frames(self, frame_paths):
        if not frame_paths:
            return
        add = messagebox.askyesno(
            "Add Frames?",
            f"Extracted {len(frame_paths)} frames.\nAdd to the media list?")
        if add:
            existing = {m["path"] for m in self.media_files}
            for fp in frame_paths:
                if fp not in existing:
                    entry = {"path": fp, "type": "image"}
                    self.media_files.append(entry)
                    self.file_listbox.insert(tk.END, _listbox_display(entry))
            self._rebuild_thumb_strip()
            self.status_var.set(f"Added {len(frame_paths)} extracted frames")

    # -- Convert Format --

    def convert_format(self):
        if not self._require_ffmpeg():
            return
        path = self._get_selected_video_path()
        if not path:
            messagebox.showinfo("Convert Format", "Select a video file first.")
            return
        base = os.path.splitext(os.path.basename(path))[0]
        output_file = filedialog.asksaveasfilename(
            title="Save Converted Video As", initialfile=base,
            filetypes=[("MP4", "*.mp4"), ("MKV", "*.mkv"), ("AVI", "*.avi"),
                       ("MOV", "*.mov"), ("WebM", "*.webm"), ("All", "*.*")],
        )
        if not output_file:
            return

        def op(cb):
            video_ops.convert_format(path, output_file, progress_callback=cb)
            return f"Converted video saved to:\n{output_file}"
        self._run_video_op("Converting Video", op)

    # -- Create GIF --

    def create_gif(self):
        if not self._require_ffmpeg():
            return
        path = self._get_selected_video_path()
        if not path:
            messagebox.showinfo("Create GIF", "Select a video file first.")
            return
        fps = simpledialog.askinteger("GIF FPS", "Frames per second:",
                                      initialvalue=10, minvalue=1, maxvalue=30,
                                      parent=self.root)
        if fps is None:
            return
        width = simpledialog.askinteger("GIF Width", "Width in pixels:",
                                        initialvalue=480, minvalue=100,
                                        maxvalue=3840, parent=self.root)
        if width is None:
            return
        base = os.path.splitext(os.path.basename(path))[0]
        output_file = filedialog.asksaveasfilename(
            title="Save GIF As", initialfile=f"{base}.gif",
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
            initialfile=default_name, defaultextension=ext,
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
        """Fast metadata strip (stream copy, removes global/stream/chapter metadata
        plus owner, computer, GPS, EXIF, XMP info using bitexact flags)."""
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
            initialfile=default_name, defaultextension=ext,
            filetypes=[("Video files", f"*{ext}"), ("All files", "*.*")],
        )
        if not output_file:
            return

        def op(cb):
            video_ops.strip_metadata(path, output_file, progress_callback=cb)
            return (f"Metadata stripped (fast mode).\n"
                    f"Removed: global, stream, chapter metadata + encoder info.\n"
                    f"Saved to:\n{output_file}")
        self._run_video_op("Stripping Metadata", op)

    def strip_metadata_deep(self):
        """Deep metadata strip - re-encodes to guarantee complete removal of ALL
        metadata including owner info, computer name, GPS, EXIF, XMP, and any
        container-specific tags."""
        if not self._require_ffmpeg():
            return
        path = self._get_selected_video_path()
        if not path:
            messagebox.showinfo("Strip Metadata (Deep)", "Select a video file first.")
            return

        if not messagebox.askyesno(
            "Deep Metadata Strip",
            "Deep strip re-encodes the video to guarantee complete removal of ALL "
            "metadata including:\n\n"
            "- Owner / author information\n"
            "- Computer name / hostname\n"
            "- GPS / location data\n"
            "- EXIF / XMP / ID3 tags\n"
            "- Encoder and creation tool info\n"
            "- Chapter metadata\n\n"
            "This is slower than fast strip but guarantees nothing survives.\n\n"
            "Continue?"):
            return

        base, ext = os.path.splitext(path)
        default_name = f"{os.path.basename(base)}_deep_stripped{ext}"
        output_file = filedialog.asksaveasfilename(
            title="Save Deep-Stripped Video As",
            initialfile=default_name, defaultextension=ext,
            filetypes=[("Video files", f"*{ext}"), ("All files", "*.*")],
        )
        if not output_file:
            return

        def op(cb):
            video_ops.strip_metadata_deep(path, output_file, progress_callback=cb)
            return (f"Deep metadata strip complete.\n"
                    f"All metadata removed (re-encoded).\n"
                    f"Saved to:\n{output_file}")
        self._run_video_op("Deep Stripping Metadata", op)

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
        return [
            self.media_files[i]["path"]
            for i in self.selected_indices
            if i < len(self.media_files) and self.media_files[i]["type"] == "image"
        ]

    def _apply_cv2_filter_to_selected(self, filter_fn, description="filter"):
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

    # -- Crop dialog --

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

    # -- Resize dialog --

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
                    lambda img: cv2.resize(img, (w, h),
                                           interpolation=cv2.INTER_LANCZOS4),
                    "Resize")
            except ValueError as e:
                messagebox.showerror("Error", f"Invalid value: {e}")

        ttk.Button(btn_frame, text="Apply", command=apply_resize).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy).pack(side=tk.LEFT, padx=5)

    # -- Rotate dialog --

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

    # -- Brightness dialog --

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
                "Brightness")

        ttk.Button(btn_frame, text="Apply",
                   command=apply_brightness).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel",
                   command=dlg.destroy).pack(side=tk.RIGHT, padx=5)

    # -- Contrast dialog --

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
                "Contrast")

        ttk.Button(btn_frame, text="Apply",
                   command=apply_contrast).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel",
                   command=dlg.destroy).pack(side=tk.RIGHT, padx=5)

    # -- Grayscale --

    def apply_grayscale(self):
        def _to_gray(img):
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        self._apply_cv2_filter_to_selected(_to_gray, "Grayscale")

    # -- Text overlay dialog --

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
                    return cv2.putText(img.copy(), text, (x, y),
                                       cv2.FONT_HERSHEY_SIMPLEX, fs, color, 2,
                                       cv2.LINE_AA)
                self._apply_cv2_filter_to_selected(_overlay, "Text Overlay")
            except Exception as e:
                messagebox.showerror("Error", f"Invalid input: {e}")

        ttk.Button(btn_frame, text="Apply", command=apply_text).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy).pack(side=tk.LEFT, padx=5)

    # -- Scale bar dialog --

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
                    cv2.line(out, (x, y), (x + bar_len, y), (255, 255, 255), thickness)
                    cap_h = thickness * 2
                    cv2.line(out, (x, y - cap_h), (x, y + cap_h), (255, 255, 255), thickness)
                    cv2.line(out, (x + bar_len, y - cap_h), (x + bar_len, y + cap_h),
                             (255, 255, 255), thickness)
                    cv2.putText(out, label, (x, y - cap_h - 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1,
                                cv2.LINE_AA)
                    return out

                self._apply_cv2_filter_to_selected(_bar, "Scale Bar")
            except Exception as e:
                messagebox.showerror("Error", f"Invalid input: {e}")

        ttk.Button(btn_frame, text="Apply", command=apply_scale_bar).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy).pack(side=tk.LEFT, padx=5)

    # -- Timestamp dialog --

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

        ttk.Label(frame, text="Batch Processing",
                  font=("TkDefaultFont", 11, "bold")).pack(anchor=tk.W, pady=(0, 10))
        ttk.Label(frame, text="Apply a filter to all images in the list.").pack(
            anchor=tk.W, pady=(0, 10))

        filter_var = tk.StringVar(value="grayscale")
        filters = ["grayscale", "resize", "rotate", "brightness", "contrast"]
        ttk.Label(frame, text="Select filter:").pack(anchor=tk.W)
        combo = ttk.Combobox(frame, textvariable=filter_var, values=filters,
                             state="readonly", width=20)
        combo.pack(anchor=tk.W, pady=5)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=10)

        def run_batch():
            batch.destroy()
            self.file_listbox.selection_set(0, tk.END)
            self.update_selected_indices()
            self.apply_filter(filter_var.get())

        ttk.Button(btn_frame, text="Run", command=run_batch).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel",
                   command=batch.destroy).pack(side=tk.LEFT, padx=5)

    def export_file_list(self):
        if not self.media_files:
            messagebox.showinfo("Export List", "No files to export.")
            return
        filename = filedialog.asksaveasfilename(
            title="Export File List", defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not filename:
            return
        try:
            with open(filename, "w") as f:
                for entry in self.media_files:
                    f.write(f"{entry['path']}\n")
            self.status_var.set(f"File list exported to {os.path.basename(filename)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export: {e}")

    def import_file_list(self):
        filename = filedialog.askopenfilename(
            title="Import File List",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
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
            self._rebuild_thumb_strip()
            self.status_var.set(f"Imported {len(self.media_files)} file(s)")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to import: {e}")

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
4. Use the Play button or Preview to check how the movie will look.
5. Click Create Video to generate the final output.

VIDEO OPERATIONS (requires FFmpeg)
-----------------------------------
- Merge Videos: combine multiple videos into one.
- Split Video: split a video at defined time points.
- Trim Video: remove start/end portions.
- Audio operations: mute, extract, or add audio tracks.
- Mute Section: mute audio in a specific time range.
- Change Speed: speed up or slow down playback.
- Extract Frames: pull individual frames as images.
- Convert Format: transcode between video formats.
- Create GIF: convert a video to an animated GIF.

METADATA
--------
- View, edit, or strip metadata from video files.
- Strip Metadata (Fast): removes all metadata using stream copy.
- Strip Metadata (Deep): re-encodes to guarantee complete removal
  of ALL metadata including owner info, computer name, GPS, EXIF,
  XMP, ID3 tags, encoder info, and chapter metadata.

TRANSPORT CONTROLS
------------------
- Play/Pause: play images as slideshow or video files frame by frame.
- Stop: stop and reset to beginning.
- << / >>: jump to first/last frame.
- < / >: step one frame backward/forward.
- Position slider: seek to any position.
- Crop Region: draw a rectangle on preview to crop.
- Trim Section / Mute Section: quick access to trim/mute tools.

THUMBNAIL STRIP
---------------
- Shows thumbnails of all media files or video frames.
- Click a thumbnail to jump to that position.
- Scroll horizontally with mouse wheel.
- Thumbnails load in the background for performance.

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
                f"Version: {status['version']}")
        else:
            text = "FFmpeg was NOT found on this system.\n\n" + get_ffmpeg_help_text()
        FFmpegHelpDialog(self.root, text)

    def check_for_ffmpeg(self):
        import simmovimaker.ffmpeg_utils as _fu
        _fu._ffmpeg_path_cache = None
        _fu._ffprobe_path_cache = None
        self.status_var.set("Checking for FFmpeg...")
        threading.Thread(target=self._check_ffmpeg_async, daemon=True).start()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    root = tk.Tk()
    root.minsize(900, 700)
    app = SimMovieMaker(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
