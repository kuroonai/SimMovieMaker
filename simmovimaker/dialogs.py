"""
Reusable tkinter dialog classes for the SimMovieMaker application.
"""

import os
import re
import tkinter as tk
from tkinter import ttk, messagebox


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def format_duration(seconds):
    """Convert a float number of seconds to an HH:MM:SS.mmm string."""
    if seconds is None or seconds < 0:
        return "00:00:00.000"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    whole_secs = int(secs)
    millis = int(round((secs - whole_secs) * 1000))
    return f"{hours:02d}:{minutes:02d}:{whole_secs:02d}.{millis:03d}"


def parse_duration(time_str):
    """Convert an HH:MM:SS.mmm (or plain seconds) string to float seconds.

    Accepted formats:
        ``HH:MM:SS.mmm``
        ``HH:MM:SS``
        ``MM:SS.mmm``
        ``MM:SS``
        ``SS.mmm``
        ``SS``  (plain number)
    """
    time_str = time_str.strip()
    # Try plain number first
    try:
        return float(time_str)
    except ValueError:
        pass

    pattern = r"^(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)$"
    match = re.match(pattern, time_str)
    if match:
        hours = int(match.group(1)) if match.group(1) else 0
        minutes = int(match.group(2))
        secs = float(match.group(3))
        return hours * 3600 + minutes * 60 + secs

    raise ValueError(f"Cannot parse time string: '{time_str}'")


# ---------------------------------------------------------------------------
# Icon helper
# ---------------------------------------------------------------------------

def _set_dialog_icon(dialog):
    """Attempt to set the dialog window icon to smm.ico in the assets folder."""
    try:
        assets_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
        ico_path = os.path.join(assets_dir, "smm.ico")
        if not os.path.isfile(ico_path):
            # Fall back to the repository root
            ico_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "smm.ico")
        if os.path.isfile(ico_path):
            dialog.iconbitmap(ico_path)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 1. BaseDialog
# ---------------------------------------------------------------------------

class BaseDialog(tk.Toplevel):
    """Base dialog that all other dialogs inherit from.

    Subclasses should override ``body(frame)`` to populate the dialog and
    ``apply()`` to handle the OK action.  The ``result`` attribute holds
    the return value (``None`` if cancelled).
    """

    def __init__(self, parent, title="Dialog", size=None):
        super().__init__(parent)
        self.transient(parent)
        self.title(title)
        self.result = None
        self._parent = parent

        _set_dialog_icon(self)

        # Content frame
        body_frame = ttk.Frame(self, padding=10)
        body_frame.pack(fill=tk.BOTH, expand=True)
        self.body(body_frame)

        # Button bar
        btn_frame = ttk.Frame(self, padding=(10, 0, 10, 10))
        btn_frame.pack(fill=tk.X)
        self._create_buttons(btn_frame)

        if size:
            self.geometry(f"{size[0]}x{size[1]}")

        self._center_on_parent()
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", lambda e: self._on_cancel())

    # Overridable -----------------------------------------------------------

    def body(self, frame):
        """Override to build dialog content inside *frame*."""
        pass

    def apply(self):
        """Override to process the dialog result (set ``self.result``)."""
        pass

    def _create_buttons(self, frame):
        """Create OK / Cancel buttons.  Override to customise."""
        ok_btn = ttk.Button(frame, text="OK", command=self._on_ok, width=10)
        ok_btn.pack(side=tk.RIGHT, padx=(5, 0))
        cancel_btn = ttk.Button(frame, text="Cancel", command=self._on_cancel, width=10)
        cancel_btn.pack(side=tk.RIGHT)

    # Internal --------------------------------------------------------------

    def _on_ok(self):
        self.apply()
        self.grab_release()
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.grab_release()
        self.destroy()

    def _center_on_parent(self):
        self.update_idletasks()
        pw = self._parent.winfo_width()
        ph = self._parent.winfo_height()
        px = self._parent.winfo_rootx()
        py = self._parent.winfo_rooty()
        w = self.winfo_width()
        h = self.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        self.geometry(f"+{x}+{y}")


# ---------------------------------------------------------------------------
# 2. ProgressDialog
# ---------------------------------------------------------------------------

class ProgressDialog(tk.Toplevel):
    """Non-blocking progress dialog with an optional cancel button.

    Usage::

        dlg = ProgressDialog(parent, "Working...")
        dlg.update_progress(50, "Half done")
        if dlg.cancelled:
            ...
        dlg.destroy()
    """

    def __init__(self, parent, title="Progress", maximum=100, cancelable=True):
        super().__init__(parent)
        self.transient(parent)
        self.title(title)
        self._cancelled = False
        self._parent = parent

        _set_dialog_icon(self)
        self.resizable(False, False)

        frame = ttk.Frame(self, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        self._label = ttk.Label(frame, text="")
        self._label.pack(anchor=tk.W, pady=(0, 5))

        self._progress = ttk.Progressbar(frame, orient=tk.HORIZONTAL,
                                         length=350, mode="determinate",
                                         maximum=maximum)
        self._progress.pack(fill=tk.X)

        if cancelable:
            btn_frame = ttk.Frame(self, padding=(15, 5, 15, 15))
            btn_frame.pack(fill=tk.X)
            self._cancel_btn = ttk.Button(btn_frame, text="Cancel",
                                          command=self._on_cancel, width=10)
            self._cancel_btn.pack(side=tk.RIGHT)

        # Centre on parent
        self.update_idletasks()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        w = self.winfo_width()
        h = self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    @property
    def cancelled(self):
        return self._cancelled

    def update_progress(self, value, text=None):
        """Set the progress bar value and optionally update the label text."""
        self._progress["value"] = value
        if text is not None:
            self._label.config(text=text)
        self.update_idletasks()

    def _on_cancel(self):
        self._cancelled = True


# ---------------------------------------------------------------------------
# 3. VideoInfoDialog
# ---------------------------------------------------------------------------

class VideoInfoDialog(BaseDialog):
    """Read-only dialog showing video file information."""

    def __init__(self, parent, info_dict):
        self._info = info_dict
        super().__init__(parent, title="Video Information", size=(420, 320))

    def body(self, frame):
        labels = [
            ("Duration", "duration"),
            ("Resolution", "resolution"),
            ("FPS", "fps"),
            ("Codec", "codec"),
            ("Audio", "audio"),
            ("Bitrate", "bitrate"),
            ("File Size", "file_size"),
        ]
        for row, (display, key) in enumerate(labels):
            ttk.Label(frame, text=f"{display}:", font=("TkDefaultFont", 9, "bold")).grid(
                row=row, column=0, sticky=tk.W, padx=(0, 15), pady=3)
            value = self._info.get(key, "N/A")
            ttk.Label(frame, text=str(value)).grid(
                row=row, column=1, sticky=tk.W, pady=3)

    def _create_buttons(self, frame):
        ttk.Button(frame, text="Close", command=self._on_cancel, width=10).pack(side=tk.RIGHT)


# ---------------------------------------------------------------------------
# 4. MetadataDialog
# ---------------------------------------------------------------------------

class MetadataDialog(BaseDialog):
    """Editable metadata dialog with a treeview table."""

    def __init__(self, parent, metadata_dict):
        self._metadata = dict(metadata_dict) if metadata_dict else {}
        super().__init__(parent, title="Edit Metadata", size=(500, 400))

    def body(self, frame):
        # Treeview
        cols = ("Tag", "Value")
        self._tree = ttk.Treeview(frame, columns=cols, show="headings", height=12)
        self._tree.heading("Tag", text="Tag")
        self._tree.heading("Value", text="Value")
        self._tree.column("Tag", width=160)
        self._tree.column("Value", width=280)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)

        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y)

        # Populate
        for tag, value in self._metadata.items():
            self._tree.insert("", tk.END, values=(tag, value))

        # Action buttons on the right
        action_frame = ttk.Frame(frame, padding=(10, 0, 0, 0))
        action_frame.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Button(action_frame, text="Add Tag", command=self._add_tag, width=12).pack(pady=(0, 5))
        ttk.Button(action_frame, text="Edit Tag", command=self._edit_tag, width=12).pack(pady=(0, 5))
        ttk.Button(action_frame, text="Delete Tag", command=self._delete_tag, width=12).pack()

    def _add_tag(self):
        dlg = _TagEntryDialog(self, "Add Tag")
        if dlg.result:
            tag, value = dlg.result
            self._tree.insert("", tk.END, values=(tag, value))

    def _edit_tag(self):
        sel = self._tree.selection()
        if not sel:
            return
        item = sel[0]
        old_tag, old_value = self._tree.item(item, "values")
        dlg = _TagEntryDialog(self, "Edit Tag", old_tag, old_value)
        if dlg.result:
            tag, value = dlg.result
            self._tree.item(item, values=(tag, value))

    def _delete_tag(self):
        sel = self._tree.selection()
        if sel:
            self._tree.delete(*sel)

    def apply(self):
        self.result = {}
        for item in self._tree.get_children():
            tag, value = self._tree.item(item, "values")
            self.result[tag] = value

    def get_metadata(self):
        """Return the metadata dict (available after dialog closes with OK)."""
        return self.result if self.result is not None else dict(self._metadata)


class _TagEntryDialog(BaseDialog):
    """Small helper dialog for entering a single tag/value pair."""

    def __init__(self, parent, title, tag="", value=""):
        self._init_tag = tag
        self._init_value = value
        super().__init__(parent, title=title, size=(350, 140))

    def body(self, frame):
        ttk.Label(frame, text="Tag:").grid(row=0, column=0, sticky=tk.W, pady=3)
        self._tag_var = tk.StringVar(value=self._init_tag)
        ttk.Entry(frame, textvariable=self._tag_var, width=35).grid(row=0, column=1, pady=3)

        ttk.Label(frame, text="Value:").grid(row=1, column=0, sticky=tk.W, pady=3)
        self._value_var = tk.StringVar(value=self._init_value)
        ttk.Entry(frame, textvariable=self._value_var, width=35).grid(row=1, column=1, pady=3)

    def apply(self):
        tag = self._tag_var.get().strip()
        value = self._value_var.get().strip()
        if tag:
            self.result = (tag, value)


# ---------------------------------------------------------------------------
# 5. SplitVideoDialog
# ---------------------------------------------------------------------------

class SplitVideoDialog(BaseDialog):
    """Dialog for defining split points within a video."""

    def __init__(self, parent, duration):
        self._duration = duration
        self._split_points = []
        super().__init__(parent, title="Split Video", size=(420, 380))

    def body(self, frame):
        info_text = f"Video duration: {format_duration(self._duration)}  ({self._duration:.3f}s)"
        ttk.Label(frame, text=info_text).pack(anchor=tk.W, pady=(0, 8))

        # Entry row
        entry_frame = ttk.Frame(frame)
        entry_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(entry_frame, text="Split at:").pack(side=tk.LEFT)
        self._time_var = tk.StringVar()
        self._time_entry = ttk.Entry(entry_frame, textvariable=self._time_var, width=18)
        self._time_entry.pack(side=tk.LEFT, padx=5)
        ttk.Label(entry_frame, text="(HH:MM:SS.mmm or seconds)").pack(side=tk.LEFT)

        # Buttons row
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(btn_frame, text="Add", command=self._add_point, width=10).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="Remove", command=self._remove_point, width=10).pack(side=tk.LEFT)

        # Listbox
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self._listbox = tk.Listbox(list_frame, height=10)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self._listbox.yview)
        self._listbox.configure(yscrollcommand=scrollbar.set)
        self._listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y)

    def _add_point(self):
        raw = self._time_var.get().strip()
        if not raw:
            return
        try:
            secs = parse_duration(raw)
        except ValueError:
            messagebox.showerror("Invalid Time", f"Cannot parse '{raw}' as a time value.", parent=self)
            return
        if secs <= 0 or secs >= self._duration:
            messagebox.showerror("Out of Range",
                                 f"Split point must be between 0 and {format_duration(self._duration)}.",
                                 parent=self)
            return
        if secs in self._split_points:
            return
        self._split_points.append(secs)
        self._split_points.sort()
        self._refresh_listbox()
        self._time_var.set("")

    def _remove_point(self):
        sel = self._listbox.curselection()
        if sel:
            idx = sel[0]
            del self._split_points[idx]
            self._refresh_listbox()

    def _refresh_listbox(self):
        self._listbox.delete(0, tk.END)
        for s in self._split_points:
            self._listbox.insert(tk.END, f"{format_duration(s)}  ({s:.3f}s)")

    def apply(self):
        self.result = list(self._split_points)


# ---------------------------------------------------------------------------
# 6. TrimDialog
# ---------------------------------------------------------------------------

class TrimDialog(BaseDialog):
    """Dialog for setting start and end trim times."""

    def __init__(self, parent, duration):
        self._duration = duration
        super().__init__(parent, title="Trim Video", size=(380, 200))

    def body(self, frame):
        info_text = f"Video duration: {format_duration(self._duration)}"
        ttk.Label(frame, text=info_text).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))

        ttk.Label(frame, text="Start time (HH:MM:SS):").grid(row=1, column=0, sticky=tk.W, pady=3)
        self._start_var = tk.StringVar(value="00:00:00")
        ttk.Entry(frame, textvariable=self._start_var, width=18).grid(row=1, column=1, sticky=tk.W, pady=3)

        ttk.Label(frame, text="End time (HH:MM:SS):").grid(row=2, column=0, sticky=tk.W, pady=3)
        self._end_var = tk.StringVar(value=format_duration(self._duration))
        ttk.Entry(frame, textvariable=self._end_var, width=18).grid(row=2, column=1, sticky=tk.W, pady=3)

    def apply(self):
        try:
            start = parse_duration(self._start_var.get())
            end = parse_duration(self._end_var.get())
        except ValueError as exc:
            messagebox.showerror("Invalid Time", str(exc), parent=self)
            return
        if start >= end:
            messagebox.showerror("Invalid Range", "Start time must be less than end time.", parent=self)
            return
        if end > self._duration:
            messagebox.showerror("Out of Range",
                                 f"End time exceeds video duration ({format_duration(self._duration)}).",
                                 parent=self)
            return
        self.result = (start, end)


# ---------------------------------------------------------------------------
# 7. SpeedDialog
# ---------------------------------------------------------------------------

class SpeedDialog(BaseDialog):
    """Dialog for choosing a playback speed factor (0.25x -- 4.0x)."""

    def __init__(self, parent):
        super().__init__(parent, title="Set Speed", size=(380, 200))

    def body(self, frame):
        ttk.Label(frame, text="Speed factor:").pack(anchor=tk.W)

        self._speed_var = tk.DoubleVar(value=1.0)

        # Scale
        self._scale = ttk.Scale(frame, from_=0.25, to=4.0,
                                orient=tk.HORIZONTAL,
                                variable=self._speed_var,
                                command=self._on_scale_change)
        self._scale.pack(fill=tk.X, pady=(5, 0))

        self._speed_label = ttk.Label(frame, text="1.00x")
        self._speed_label.pack(anchor=tk.E)

        # Presets
        preset_frame = ttk.Frame(frame)
        preset_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(preset_frame, text="Presets:").pack(side=tk.LEFT, padx=(0, 5))
        for val in (0.5, 1.0, 2.0):
            ttk.Button(preset_frame, text=f"{val}x",
                       command=lambda v=val: self._set_speed(v),
                       width=6).pack(side=tk.LEFT, padx=2)

    def _on_scale_change(self, _value=None):
        v = self._speed_var.get()
        self._speed_label.config(text=f"{v:.2f}x")

    def _set_speed(self, value):
        self._speed_var.set(value)
        self._on_scale_change()

    def apply(self):
        self.result = round(self._speed_var.get(), 2)


# ---------------------------------------------------------------------------
# 8. ExtractFramesDialog
# ---------------------------------------------------------------------------

class ExtractFramesDialog(BaseDialog):
    """Dialog for frame extraction settings."""

    def __init__(self, parent, video_fps):
        self._video_fps = video_fps
        super().__init__(parent, title="Extract Frames", size=(420, 300))

    def body(self, frame):
        ttk.Label(frame, text=f"Video FPS: {self._video_fps:.2f}").pack(anchor=tk.W, pady=(0, 10))

        # Extraction mode
        self._mode_var = tk.StringVar(value="all")

        mode_frame = ttk.LabelFrame(frame, text="Extraction mode", padding=8)
        mode_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Radiobutton(mode_frame, text="Extract all frames",
                        variable=self._mode_var, value="all",
                        command=self._on_mode_change).pack(anchor=tk.W)

        nth_row = ttk.Frame(mode_frame)
        nth_row.pack(anchor=tk.W, fill=tk.X)
        ttk.Radiobutton(nth_row, text="Every",
                        variable=self._mode_var, value="nth",
                        command=self._on_mode_change).pack(side=tk.LEFT)
        self._nth_var = tk.IntVar(value=10)
        self._nth_spin = ttk.Spinbox(nth_row, from_=2, to=9999, width=6,
                                     textvariable=self._nth_var)
        self._nth_spin.pack(side=tk.LEFT, padx=3)
        ttk.Label(nth_row, text="frames").pack(side=tk.LEFT)

        fps_row = ttk.Frame(mode_frame)
        fps_row.pack(anchor=tk.W, fill=tk.X)
        ttk.Radiobutton(fps_row, text="At FPS:",
                        variable=self._mode_var, value="fps",
                        command=self._on_mode_change).pack(side=tk.LEFT)
        self._fps_var = tk.DoubleVar(value=1.0)
        self._fps_spin = ttk.Spinbox(fps_row, from_=0.1, to=self._video_fps,
                                     increment=0.5, width=8,
                                     textvariable=self._fps_var)
        self._fps_spin.pack(side=tk.LEFT, padx=3)

        # Output format
        fmt_frame = ttk.LabelFrame(frame, text="Output format", padding=8)
        fmt_frame.pack(fill=tk.X)

        self._fmt_var = tk.StringVar(value="PNG")
        for fmt in ("PNG", "JPG", "BMP"):
            ttk.Radiobutton(fmt_frame, text=fmt, variable=self._fmt_var,
                            value=fmt).pack(side=tk.LEFT, padx=(0, 15))

        self._on_mode_change()

    def _on_mode_change(self):
        mode = self._mode_var.get()
        state_nth = "normal" if mode == "nth" else "disabled"
        state_fps = "normal" if mode == "fps" else "disabled"
        self._nth_spin.config(state=state_nth)
        self._fps_spin.config(state=state_fps)

    def apply(self):
        mode = self._mode_var.get()
        settings = {
            "mode": mode,
            "format": self._fmt_var.get(),
        }
        if mode == "nth":
            settings["nth"] = self._nth_var.get()
        elif mode == "fps":
            settings["fps"] = self._fps_var.get()
        self.result = settings


# ---------------------------------------------------------------------------
# 9. FFmpegHelpDialog
# ---------------------------------------------------------------------------

class FFmpegHelpDialog(BaseDialog):
    """Display FFmpeg installation help in a scrollable text widget."""

    def __init__(self, parent, help_text):
        self._help_text = help_text
        super().__init__(parent, title="FFmpeg Help", size=(560, 420))

    def body(self, frame):
        text_widget = tk.Text(frame, wrap=tk.WORD, padx=8, pady=8)
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y)

        text_widget.insert(tk.END, self._help_text)
        text_widget.config(state=tk.DISABLED)

    def _create_buttons(self, frame):
        ttk.Button(frame, text="Close", command=self._on_cancel, width=10).pack(side=tk.RIGHT)


# ---------------------------------------------------------------------------
# 10. MergeOptionsDialog
# ---------------------------------------------------------------------------

class MergeOptionsDialog(BaseDialog):
    """Options dialog for merging video files."""

    def __init__(self, parent):
        super().__init__(parent, title="Merge Options", size=(400, 220))

    def body(self, frame):
        # Method
        method_frame = ttk.LabelFrame(frame, text="Merge method", padding=8)
        method_frame.pack(fill=tk.X, pady=(0, 10))

        self._method_var = tk.StringVar(value="stream_copy")
        ttk.Radiobutton(method_frame, text="Stream copy (fast, no re-encode)",
                        variable=self._method_var,
                        value="stream_copy").pack(anchor=tk.W)
        ttk.Radiobutton(method_frame, text="Re-encode (slower, ensures compatibility)",
                        variable=self._method_var,
                        value="reencode").pack(anchor=tk.W)

        # Output format
        fmt_frame = ttk.LabelFrame(frame, text="Output format", padding=8)
        fmt_frame.pack(fill=tk.X)

        self._format_var = tk.StringVar(value="mp4")
        for fmt in ("mp4", "mkv", "avi", "mov"):
            ttk.Radiobutton(fmt_frame, text=fmt.upper(), variable=self._format_var,
                            value=fmt).pack(side=tk.LEFT, padx=(0, 15))

    def apply(self):
        self.result = {
            "method": self._method_var.get(),
            "format": self._format_var.get(),
        }
