"""
SimMovieMaker - A software for creating movies from simulation snapshots
"""

import os
import sys
import cv2
import numpy as np
import tkinter as tk
from tkinter import filedialog, ttk
from PIL import Image, ImageTk
import json
from datetime import datetime


class SimMovieMaker:
    def __init__(self, root):
        self.root = root
        self.root.title("SimMovieMaker")
        self.root.geometry("1200x800")
        
        # Project data
        self.project_file = None
        self.image_files = []
        self.selected_indices = []
        self.current_preview_index = 0
        self.output_settings = {
            "format": "mp4",
            "fps": 30,
            "codec": "H264",
            "quality": 80
        }
        
        # Create the menu bar
        self.create_menu_bar()
        
        # Create the main layout
        self.create_layout()
        
    def create_menu_bar(self):
        menubar = tk.Menu(self.root)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Project", command=self.new_project)
        file_menu.add_command(label="Open Project", command=self.open_project)
        file_menu.add_command(label="Save Project", command=self.save_project)
        file_menu.add_command(label="Save Project As", command=self.save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Import Images", command=self.import_images)
        file_menu.add_command(label="Import Sequence", command=self.import_sequence)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        
        # Edit menu
        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Select All", command=self.select_all)
        edit_menu.add_command(label="Deselect All", command=self.deselect_all)
        edit_menu.add_separator()
        edit_menu.add_command(label="Delete Selected", command=self.delete_selected)
        edit_menu.add_separator()
        edit_menu.add_command(label="Move Up", command=lambda: self.move_selected(-1))
        edit_menu.add_command(label="Move Down", command=lambda: self.move_selected(1))
        menubar.add_cascade(label="Edit", menu=edit_menu)
        
        # Preview menu
        preview_menu = tk.Menu(menubar, tearoff=0)
        preview_menu.add_command(label="Preview Current Frame", command=self.preview_current)
        preview_menu.add_command(label="Create Preview Video", command=self.create_preview)
        menubar.add_cascade(label="Preview", menu=preview_menu)
        
        # Video menu
        video_menu = tk.Menu(menubar, tearoff=0)
        video_menu.add_command(label="Output Settings", command=self.show_output_settings)
        video_menu.add_separator()
        video_menu.add_command(label="Create Video", command=self.create_video)
        menubar.add_cascade(label="Video", menu=video_menu)
        
        # Video Filters menu
        filter_menu = tk.Menu(menubar, tearoff=0)
        
        # Size submenu
        size_menu = tk.Menu(filter_menu, tearoff=0)
        size_menu.add_command(label="Crop", command=lambda: self.apply_filter("crop"))
        size_menu.add_command(label="Resize", command=lambda: self.apply_filter("resize"))
        size_menu.add_command(label="Rotate", command=lambda: self.apply_filter("rotate"))
        filter_menu.add_cascade(label="Adjust Size", menu=size_menu)
        
        # Color submenu
        color_menu = tk.Menu(filter_menu, tearoff=0)
        color_menu.add_command(label="Brightness", command=lambda: self.apply_filter("brightness"))
        color_menu.add_command(label="Contrast", command=lambda: self.apply_filter("contrast"))
        color_menu.add_command(label="Grayscale", command=lambda: self.apply_filter("grayscale"))
        filter_menu.add_cascade(label="Adjust Colors", menu=color_menu)
        
        # Overlay submenu
        overlay_menu = tk.Menu(filter_menu, tearoff=0)
        overlay_menu.add_command(label="Text Overlay", command=lambda: self.apply_filter("text_overlay"))
        overlay_menu.add_command(label="Scale Bar", command=lambda: self.apply_filter("scale_bar"))
        overlay_menu.add_command(label="Timestamp", command=lambda: self.apply_filter("timestamp"))
        filter_menu.add_cascade(label="Overlay", menu=overlay_menu)
        
        menubar.add_cascade(label="Filters", menu=filter_menu)
        
        # Tools menu
        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="Batch Process", command=self.batch_process)
        tools_menu.add_command(label="Export File List", command=self.export_file_list)
        tools_menu.add_command(label="Import File List", command=self.import_file_list)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Documentation", command=self.show_documentation)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)
        
        self.root.config(menu=menubar)
    
    def create_layout(self):
        # Main frame
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Split into left and right panels
        panel = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        panel.pack(fill=tk.BOTH, expand=True)
        
        # Left panel - File list
        left_frame = ttk.Frame(panel, width=400)
        panel.add(left_frame)
        
        # File list label
        ttk.Label(left_frame, text="File List").pack(anchor=tk.W, pady=(0, 5))
        
        # File list with scrollbar
        list_frame = ttk.Frame(left_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        self.file_listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED)
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.file_listbox.bind('<<ListboxSelect>>', self.on_file_select)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.file_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_listbox.config(yscrollcommand=scrollbar.set)
        
        # Button frame
        button_frame = ttk.Frame(left_frame)
        button_frame.pack(fill=tk.X, pady=5)
        
        ttk.Button(button_frame, text="Add Files", command=self.import_images).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="Remove", command=self.delete_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="↑", width=2, command=lambda: self.move_selected(-1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="↓", width=2, command=lambda: self.move_selected(1)).pack(side=tk.LEFT, padx=2)
        
        # Right panel - Preview and properties
        right_frame = ttk.Frame(panel)
        panel.add(right_frame)
        
        # Preview label
        ttk.Label(right_frame, text="Preview").pack(anchor=tk.W, pady=(0, 5))
        
        # Preview frame
        self.preview_frame = ttk.Frame(right_frame, relief=tk.SUNKEN, borderwidth=1)
        self.preview_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Create a canvas for the preview image
        self.preview_canvas = tk.Canvas(self.preview_frame, bg="black")
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)
        
        # Preview controls
        controls_frame = ttk.Frame(right_frame)
        controls_frame.pack(fill=tk.X, pady=5)
        
        ttk.Button(controls_frame, text="◀◀", width=3, command=self.preview_first).pack(side=tk.LEFT, padx=2)
        ttk.Button(controls_frame, text="◀", width=3, command=self.preview_previous).pack(side=tk.LEFT, padx=2)
        
        self.preview_label = ttk.Label(controls_frame, text="0/0")
        self.preview_label.pack(side=tk.LEFT, padx=10)
        
        ttk.Button(controls_frame, text="▶", width=3, command=self.preview_next).pack(side=tk.LEFT, padx=2)
        ttk.Button(controls_frame, text="▶▶", width=3, command=self.preview_last).pack(side=tk.LEFT, padx=2)
        ttk.Button(controls_frame, text="Preview Video", command=self.create_preview).pack(side=tk.RIGHT, padx=2)
        
        # Properties frame
        properties_frame = ttk.LabelFrame(right_frame, text="Properties")
        properties_frame.pack(fill=tk.X, pady=10)
        
        # FPS setting
        fps_frame = ttk.Frame(properties_frame)
        fps_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(fps_frame, text="FPS:").pack(side=tk.LEFT)
        self.fps_var = tk.StringVar(value=str(self.output_settings["fps"]))
        fps_spinbox = ttk.Spinbox(fps_frame, from_=1, to=120, textvariable=self.fps_var, width=5)
        fps_spinbox.pack(side=tk.LEFT, padx=5)
        fps_spinbox.bind("<<SpinboxSelected>>", self.update_fps)
        
        # Output format
        format_frame = ttk.Frame(properties_frame)
        format_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(format_frame, text="Format:").pack(side=tk.LEFT)
        self.format_var = tk.StringVar(value=self.output_settings["format"])
        format_combo = ttk.Combobox(format_frame, textvariable=self.format_var, 
                                    values=["mp4", "avi", "mov"], width=5)
        format_combo.pack(side=tk.LEFT, padx=5)
        format_combo.bind("<<ComboboxSelected>>", self.update_format)
        
        # Codec
        codec_frame = ttk.Frame(properties_frame)
        codec_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(codec_frame, text="Codec:").pack(side=tk.LEFT)
        self.codec_var = tk.StringVar(value=self.output_settings["codec"])
        codec_combo = ttk.Combobox(codec_frame, textvariable=self.codec_var, 
                                  values=["H264", "MJPG", "XVID"], width=5)
        codec_combo.pack(side=tk.LEFT, padx=5)
        codec_combo.bind("<<ComboboxSelected>>", self.update_codec)
        
        # Create video button
        ttk.Button(right_frame, text="Create Video", command=self.create_video).pack(anchor=tk.E, pady=10)
        
        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
    
    # File menu functions
    def new_project(self):
        self.project_file = None
        self.image_files = []
        self.selected_indices = []
        self.current_preview_index = 0
        self.file_listbox.delete(0, tk.END)
        self.update_preview()
        self.status_var.set("New project created")
    
    def open_project(self):
        filename = filedialog.askopenfilename(
            title="Open Project",
            filetypes=[("SimMovieMaker Project", "*.smp"), ("All files", "*.*")]
        )
        if not filename:
            return
        
        try:
            with open(filename, 'r') as f:
                project_data = json.load(f)
            
            self.project_file = filename
            self.image_files = project_data.get("image_files", [])
            self.output_settings = project_data.get("output_settings", self.output_settings)
            
            # Update UI
            self.file_listbox.delete(0, tk.END)
            for img in self.image_files:
                self.file_listbox.insert(tk.END, os.path.basename(img))
            
            self.fps_var.set(str(self.output_settings["fps"]))
            self.format_var.set(self.output_settings["format"])
            self.codec_var.set(self.output_settings["codec"])
            
            self.current_preview_index = 0
            self.update_preview()
            self.status_var.set(f"Project loaded: {os.path.basename(filename)}")
        except Exception as e:
            tk.messagebox.showerror("Error", f"Failed to open project: {str(e)}")
    
    def save_project(self):
        if not self.project_file:
            self.save_project_as()
            return
        
        self._save_project(self.project_file)
    
    def save_project_as(self):
        filename = filedialog.asksaveasfilename(
            title="Save Project As",
            defaultextension=".smp",
            filetypes=[("SimMovieMaker Project", "*.smp"), ("All files", "*.*")]
        )
        if not filename:
            return
        
        self.project_file = filename
        self._save_project(filename)
    
    def _save_project(self, filename):
        project_data = {
            "image_files": self.image_files,
            "output_settings": self.output_settings,
            "saved_at": datetime.now().isoformat()
        }
        
        try:
            with open(filename, 'w') as f:
                json.dump(project_data, f, indent=2)
            self.status_var.set(f"Project saved: {os.path.basename(filename)}")
        except Exception as e:
            tk.messagebox.showerror("Error", f"Failed to save project: {str(e)}")
    
    def import_images(self):
        filenames = filedialog.askopenfilenames(
            title="Select Image Files",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp"),
                ("All files", "*.*")
            ]
        )
        if not filenames:
            return
        
        # Add the files to our list
        for filename in filenames:
            if filename not in self.image_files:
                self.image_files.append(filename)
                self.file_listbox.insert(tk.END, os.path.basename(filename))
        
        self.status_var.set(f"Added {len(filenames)} files")
        if not self.image_files:
            return
        
        # Update preview if we just added the first images
        if len(self.image_files) == len(filenames):
            self.current_preview_index = 0
            self.update_preview()
    
    def import_sequence(self):
        # First, get the directory
        directory = filedialog.askdirectory(title="Select Directory with Image Sequence")
        if not directory:
            return
        
        # Ask for a pattern - now using the standard function since we patched the Dialog class
        pattern = tk.simpledialog.askstring(
            "Image Sequence", 
            "Enter filename pattern (e.g. 'frame_*.png' or use * as wildcard):",
            initialvalue="*.png",
            parent=self.root
        )
        if not pattern:
            return
        if not pattern:
            return
        
        # Replace * with a regex wildcard
        import re
        import glob
        
        # Convert the glob pattern to a regex pattern
        regex_pattern = pattern.replace(".", r"\.").replace("*", ".*")
        
        # Get all files in the directory
        files = sorted(os.listdir(directory))
        
        # Filter files by pattern
        matching_files = [f for f in files if re.match(regex_pattern, f)]
        
        if not matching_files:
            tk.messagebox.showinfo("No files found", f"No files matching pattern '{pattern}' found in the selected directory.")
            return
        
        # Add matching files to our list
        for filename in matching_files:
            full_path = os.path.join(directory, filename)
            if full_path not in self.image_files:
                self.image_files.append(full_path)
                self.file_listbox.insert(tk.END, filename)
        
        self.status_var.set(f"Added {len(matching_files)} files from sequence")
        
        # Update preview if we just added the first images
        if len(self.image_files) > 0 and self.current_preview_index == 0:
            self.update_preview()
    
    # Edit menu functions
    def select_all(self):
        self.file_listbox.selection_set(0, tk.END)
        self.update_selected_indices()
    
    def deselect_all(self):
        self.file_listbox.selection_clear(0, tk.END)
        self.selected_indices = []
    
    def delete_selected(self):
        if not self.selected_indices:
            return
        
        # Sort indices in reverse order to avoid index shifting during deletion
        indices = sorted(self.selected_indices, reverse=True)
        
        # Remove from list and listbox
        for idx in indices:
            del self.image_files[idx]
            self.file_listbox.delete(idx)
        
        # Reset selection
        self.selected_indices = []
        
        # Update preview
        if self.image_files:
            self.current_preview_index = min(self.current_preview_index, len(self.image_files) - 1)
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
        
        # Check bounds
        if target_idx < 0 or target_idx >= len(self.image_files):
            return
        
        # Swap items in the list
        self.image_files[idx], self.image_files[target_idx] = \
            self.image_files[target_idx], self.image_files[idx]
        
        # Update listbox
        self.file_listbox.delete(idx)
        self.file_listbox.insert(target_idx, os.path.basename(self.image_files[target_idx]))
        
        # Update selection
        self.file_listbox.selection_clear(0, tk.END)
        self.file_listbox.selection_set(target_idx)
        self.selected_indices = [target_idx]
        
        # Update preview if we moved the current preview image
        if idx == self.current_preview_index:
            self.current_preview_index = target_idx
            self.update_preview()
    
    # Preview functions
    def preview_current(self):
        if not self.image_files:
            return
        self.update_preview()
    
    def preview_first(self):
        if not self.image_files:
            return
        self.current_preview_index = 0
        self.update_preview()
    
    def preview_previous(self):
        if not self.image_files:
            return
        self.current_preview_index = max(0, self.current_preview_index - 1)
        self.update_preview()
    
    def preview_next(self):
        if not self.image_files:
            return
        self.current_preview_index = min(len(self.image_files) - 1, self.current_preview_index + 1)
        self.update_preview()
    
    def preview_last(self):
        if not self.image_files:
            return
        self.current_preview_index = len(self.image_files) - 1
        self.update_preview()
    
    def update_preview(self):
        if not self.image_files:
            self.preview_canvas.delete("all")
            self.preview_label.config(text="0/0")
            return
        
        # Load the image
        image_path = self.image_files[self.current_preview_index]
        try:
            img = Image.open(image_path)
            
            # Resize to fit canvas
            canvas_width = self.preview_canvas.winfo_width()
            canvas_height = self.preview_canvas.winfo_height()
            
            if canvas_width <= 1 or canvas_height <= 1:  # Canvas not ready yet
                self.preview_canvas.after(100, self.update_preview)
                return
            
            img_width, img_height = img.size
            
            # Calculate scaling factor to fit in canvas
            scale = min(canvas_width / img_width, canvas_height / img_height)
            new_width = int(img_width * scale)
            new_height = int(img_height * scale)
            
            # Resize image
            img_resized = img.resize((new_width, new_height), Image.LANCZOS)
            
            # Convert to PhotoImage
            photo = ImageTk.PhotoImage(img_resized)
            
            # Keep a reference to prevent garbage collection
            self.current_photo = photo
            
            # Display in canvas
            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(
                canvas_width // 2, canvas_height // 2,
                image=photo, anchor=tk.CENTER
            )
            
            # Update label
            self.preview_label.config(
                text=f"{self.current_preview_index + 1}/{len(self.image_files)}"
            )
            
            # Display file info in status bar
            img_info = f"{os.path.basename(image_path)} - {img_width}x{img_height}"
            self.status_var.set(img_info)
            
        except Exception as e:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                self.preview_canvas.winfo_width() // 2,
                self.preview_canvas.winfo_height() // 2,
                text=f"Error loading image: {str(e)}",
                fill="white"
            )
    
    # Custom dialog functions that apply our icon
    def custom_askinteger(self, title, prompt, **kw):
        """Custom askinteger function that applies our icon to the dialog"""
        # Call the original askinteger
        result = tk.simpledialog.askinteger(title, prompt, **kw, parent=self.root)
        
        # Find the dialog window and set its icon
        # This needs to happen after the dialog is shown but before it's closed
        for widget in self.root.winfo_children():
            if isinstance(widget, tk.Toplevel) and widget.winfo_exists():
                if widget.title() == title:
                    try:
                        if os.path.exists(self.icon_path):
                            widget.iconbitmap(self.icon_path)
                    except Exception:
                        pass  # Silently fail if icon cannot be set
        
        return result
    
    def custom_askstring(self, title, prompt, **kw):
        """Custom askstring function that applies our icon to the dialog"""
        # Call the original askstring
        result = tk.simpledialog.askstring(title, prompt, **kw, parent=self.root)
        
        # Find the dialog window and set its icon
        for widget in self.root.winfo_children():
            if isinstance(widget, tk.Toplevel) and widget.winfo_exists():
                if widget.title() == title:
                    try:
                        if os.path.exists(self.icon_path):
                            widget.iconbitmap(self.icon_path)
                    except Exception:
                        pass  # Silently fail if icon cannot be set
        
        return result
        
    def create_preview(self):
        if not self.image_files or len(self.image_files) < 2:
            tk.messagebox.showinfo("Preview", "Need at least 2 images to create a preview.")
            return
        
        # Create a custom integer input dialog to ensure the icon is applied
        fps_dialog = tk.Toplevel(self.root)
        fps_dialog.title("Preview FPS")
        fps_dialog.geometry("300x120")
        fps_dialog.transient(self.root)
        fps_dialog.grab_set()
        fps_dialog.resizable(False, False)
        
        # Try to set the icon explicitly
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smm.ico")
        if os.path.exists(icon_path):
            try:
                fps_dialog.iconbitmap(icon_path)
            except Exception:
                pass
                
        # Add padding
        frame = ttk.Frame(fps_dialog, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Label
        ttk.Label(frame, text="Enter frames per second for preview:").pack(anchor=tk.W, pady=(0, 10))
        
        # Spinbox for fps
        fps_var = tk.IntVar(value=self.output_settings["fps"])
        fps_spinbox = ttk.Spinbox(frame, from_=1, to=60, textvariable=fps_var, width=10)
        fps_spinbox.pack(anchor=tk.W, pady=(0, 10))
        
        # Result variable
        preview_fps = [None]  # Use a list to store result (mutable)
        
        # Button frame
        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X)
        
        def on_ok():
            try:
                value = int(fps_var.get())
                if 1 <= value <= 60:
                    preview_fps[0] = value
                    fps_dialog.destroy()
                else:
                    tk.messagebox.showwarning("Invalid Input", "Value must be between 1 and 60.")
            except ValueError:
                tk.messagebox.showwarning("Invalid Input", "Please enter a valid number.")
        
        def on_cancel():
            fps_dialog.destroy()
        
        ttk.Button(button_frame, text="OK", command=on_ok).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=on_cancel).pack(side=tk.RIGHT, padx=5)
        
        # Set initial focus to the spinbox
        fps_spinbox.focus_set()
        
        # Center the dialog on the main window
        fps_dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - fps_dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - fps_dialog.winfo_height()) // 2
        fps_dialog.geometry(f"+{x}+{y}")
        
        # Wait for the dialog to close
        self.root.wait_window(fps_dialog)
        
        # Get the result
        preview_fps = preview_fps[0]
        
        if not preview_fps:
            return
        
        # Create a temporary video
        temp_output = os.path.join(os.path.expanduser("~"), "sim_preview_temp.mp4")
        
        # Preview with just the first 100 frames maximum for speed
        preview_files = self.image_files[:min(100, len(self.image_files))]
        
        # Show progress dialog
        progress = tk.Toplevel(self.root)
        progress.title("Creating Preview")
        progress.geometry("300x100")
        progress.transient(self.root)
        progress.grab_set()
        
        # If we have an icon, set it for this dialog too
        try:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smm.ico")
            if os.path.exists(icon_path):
                progress.iconbitmap(icon_path)
        except Exception:
            pass  # Silently fail if the icon cannot be set
        
        ttk.Label(progress, text="Creating preview video...").pack(pady=10)
        
        progress_bar = ttk.Progressbar(progress, mode="determinate", maximum=len(preview_files))
        progress_bar.pack(fill=tk.X, padx=20, pady=10)
        
        # Start video creation in a separate thread
        import threading
        
        def create_preview_thread():
            try:
                # Get first image to determine dimensions
                first_img = cv2.imread(preview_files[0])
                height, width = first_img.shape[:2]
                
                # Create video writer
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                out = cv2.VideoWriter(temp_output, fourcc, preview_fps, (width, height))
                
                for i, img_path in enumerate(preview_files):
                    # Update progress bar
                    progress.after(0, progress_bar.config, {"value": i + 1})
                    
                    # Read image and write to video
                    img = cv2.imread(img_path)
                    out.write(img)
                
                out.release()
                
                # Close progress and play video
                progress.after(0, progress.destroy)
                self.play_output_file(temp_output)
                
            except Exception as e:
                progress.after(0, progress.destroy)
                self.root.after(0, tk.messagebox.showerror, "Error", f"Failed to create preview: {str(e)}")
        
        threading.Thread(target=create_preview_thread, daemon=True).start()
    
    # Video functions
    def show_output_settings(self):
        # Create a dialog for output settings
        settings = tk.Toplevel(self.root)
        settings.title("Output Settings")
        settings.geometry("400x300")
        settings.transient(self.root)
        settings.grab_set()
        
        # Frame for settings
        frame = ttk.Frame(settings, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # FPS
        ttk.Label(frame, text="Frames Per Second:").grid(row=0, column=0, sticky=tk.W, pady=5)
        fps_var = tk.StringVar(value=str(self.output_settings["fps"]))
        ttk.Spinbox(frame, from_=1, to=120, textvariable=fps_var, width=10).grid(row=0, column=1, sticky=tk.W, pady=5)
        
        # Format
        ttk.Label(frame, text="Output Format:").grid(row=1, column=0, sticky=tk.W, pady=5)
        format_var = tk.StringVar(value=self.output_settings["format"])
        ttk.Combobox(frame, textvariable=format_var, values=["mp4", "avi", "mov", "webm"], width=10).grid(row=1, column=1, sticky=tk.W, pady=5)
        
        # Codec
        ttk.Label(frame, text="Video Codec:").grid(row=2, column=0, sticky=tk.W, pady=5)
        codec_var = tk.StringVar(value=self.output_settings["codec"])
        ttk.Combobox(frame, textvariable=codec_var, values=["H264", "MJPG", "XVID", "VP9"], width=10).grid(row=2, column=1, sticky=tk.W, pady=5)
        
        # Quality
        ttk.Label(frame, text="Quality (0-100):").grid(row=3, column=0, sticky=tk.W, pady=5)
        quality_var = tk.StringVar(value=str(self.output_settings["quality"]))
        ttk.Spinbox(frame, from_=0, to=100, textvariable=quality_var, width=10).grid(row=3, column=1, sticky=tk.W, pady=5)
        
        # Buttons
        button_frame = ttk.Frame(frame)
        button_frame.grid(row=4, column=0, columnspan=2, pady=20)
        
        # Save function
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
                tk.messagebox.showerror("Error", f"Invalid value: {str(e)}")
        
        ttk.Button(button_frame, text="Save", command=save_settings).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=settings.destroy).pack(side=tk.LEFT, padx=5)
    
    def create_video(self):
        if not self.image_files or len(self.image_files) < 2:
            tk.messagebox.showinfo("Create Video", "Need at least 2 images to create a video.")
            return
        
        # Ask for output file
        output_file = filedialog.asksaveasfilename(
            title="Save Video As",
            defaultextension=f".{self.output_settings['format']}",
            filetypes=[
                (f"{self.output_settings['format'].upper()} files", f"*.{self.output_settings['format']}"),
                ("All files", "*.*")
            ]
        )
        
        if not output_file:
            return
        
        # Show progress dialog
        progress = tk.Toplevel(self.root)
        progress.title("Creating Video")
        progress.geometry("300x100")
        progress.transient(self.root)
        progress.grab_set()
        
        # If we have an icon, set it for this dialog too
        try:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smm.ico")
            if os.path.exists(icon_path):
                progress.iconbitmap(icon_path)
        except Exception:
            pass  # Silently fail if the icon cannot be set
        
        ttk.Label(progress, text="Creating video...").pack(pady=10)
        
        progress_bar = ttk.Progressbar(progress, mode="determinate", maximum=len(self.image_files))
        progress_bar.pack(fill=tk.X, padx=20, pady=10)
        
        # Start video creation in a separate thread
        import threading
        
        def create_video_thread():
            try:
                # Get first image to determine dimensions
                first_img = cv2.imread(self.image_files[0])
                height, width = first_img.shape[:2]
                
                # Determine codec
                if self.output_settings["format"] == "mp4":
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                elif self.output_settings["format"] == "avi":
                    if self.output_settings["codec"] == "MJPG":
                        fourcc = cv2.VideoWriter_fourcc(*'MJPG')
                    else:
                        fourcc = cv2.VideoWriter_fourcc(*'XVID')
                elif self.output_settings["format"] == "mov":
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                else:  # default
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                
                # Create video writer
                out = cv2.VideoWriter(
                    output_file, fourcc, self.output_settings["fps"], (width, height)
                )
                
                for i, img_path in enumerate(self.image_files):
                    # Update progress bar
                    progress.after(0, progress_bar.config, {"value": i + 1})
                    
                    # Read image and write to video
                    img = cv2.imread(img_path)
                    out.write(img)
                
                out.release()
                
                # Close progress dialog
                progress.after(0, progress.destroy)
                
                # Show success message and offer to play
                play = tk.messagebox.askyesno(
                    "Success", 
                    f"Video created successfully at {output_file}. Would you like to play it now?"
                )
                if play:
                    self.play_output_file(output_file)
                
            except Exception as e:
                progress.after(0, progress.destroy)
                self.root.after(0, tk.messagebox.showerror, "Error", f"Failed to create video: {str(e)}")
        
        threading.Thread(target=create_video_thread, daemon=True).start()
    
    def play_output_file(self, file_path):
        # Try to play the video using the default system player
        import platform
        import subprocess
        
        try:
            if platform.system() == 'Darwin':  # macOS
                subprocess.call(('open', file_path))
            elif platform.system() == 'Windows':  # Windows
                os.startfile(file_path)
            else:  # Linux variants
                subprocess.call(('xdg-open', file_path))
        except Exception as e:
            tk.messagebox.showerror("Error", f"Failed to open video player: {str(e)}")
    
    # Filter functions
    def apply_filter(self, filter_name):
        if not self.selected_indices:
            tk.messagebox.showinfo("Filter", "Please select images to apply the filter to.")
            return
        
        # Implement basic filter functionality
        # In a real application, this would be much more sophisticated
        if filter_name == "crop":
            self.show_crop_dialog()
        elif filter_name == "resize":
            self.show_resize_dialog()
        elif filter_name == "rotate":
            self.show_rotate_dialog()
        elif filter_name == "brightness":
            self.show_brightness_dialog()
        elif filter_name == "contrast":
            self.show_contrast_dialog()
        elif filter_name == "grayscale":
            self.apply_grayscale()
        elif filter_name == "text_overlay":
            self.show_text_overlay_dialog()
        elif filter_name == "scale_bar":
            self.show_scale_bar_dialog()
        elif filter_name == "timestamp":
            self.show_timestamp_dialog()
    
    # Example of a filter dialog implementation
    def show_crop_dialog(self):
        # This is a simplified example - a full implementation would be more complex
        crop = tk.Toplevel(self.root)
        crop.title("Crop Images")
        crop.geometry("300x200")
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
                
                # In a real implementation, this would process the images
                tk.messagebox.showinfo("Crop", f"Crop applied: {left}, {top}, {right}, {bottom}")
                crop.destroy()
                
            except ValueError as e:
                tk.messagebox.showerror("Error", f"Invalid value: {str(e)}")
        
        ttk.Button(button_frame, text="Apply", command=apply_crop).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=crop.destroy).pack(side=tk.LEFT, padx=5)
    
    # Tool functions
    def batch_process(self):
        # Create a dialog for batch processing
        batch = tk.Toplevel(self.root)
        batch.title("Batch Process")
        batch.geometry("500x400")
        batch.transient(self.root)
        batch.grab_set()
        
        # This would be expanded in a real implementation
        ttk.Label(batch, text="Batch processing would be implemented here").pack(pady=20)
        ttk.Button(batch, text="Close", command=batch.destroy).pack()
    
    def export_file_list(self):
        if not self.image_files:
            tk.messagebox.showinfo("Export List", "No files to export.")
            return
        
        filename = filedialog.asksaveasfilename(
            title="Export File List",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        
        if not filename:
            return
        
        try:
            with open(filename, 'w') as f:
                for img_path in self.image_files:
                    f.write(f"{img_path}\n")
            
            self.status_var.set(f"File list exported to {os.path.basename(filename)}")
        except Exception as e:
            tk.messagebox.showerror("Error", f"Failed to export file list: {str(e)}")
    
    def import_file_list(self):
        filename = filedialog.askopenfilename(
            title="Import File List",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        
        if not filename:
            return
        
        try:
            with open(filename, 'r') as f:
                file_paths = [line.strip() for line in f if line.strip()]
            
            # Clear existing files
            self.image_files = []
            self.file_listbox.delete(0, tk.END)
            
            # Add new files
            for path in file_paths:
                if os.path.isfile(path):
                    self.image_files.append(path)
                    self.file_listbox.insert(tk.END, os.path.basename(path))
            
            if self.image_files:
                self.current_preview_index = 0
                self.update_preview()
            
            self.status_var.set(f"Imported {len(self.image_files)} files from list")
        except Exception as e:
            tk.messagebox.showerror("Error", f"Failed to import file list: {str(e)}")
    
    # Help functions
    def show_documentation(self):
        # In a real app, this would open documentation
        help_window = tk.Toplevel(self.root)
        help_window.title("SimMovieMaker Documentation")
        help_window.geometry("600x400")
        
        text = tk.Text(help_window, wrap=tk.WORD, padx=10, pady=10)
        text.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(text, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.config(yscrollcommand=scrollbar.set)
        
        text.insert(tk.END, """# SimMovieMaker Documentation

SimMovieMaker is a software designed for creating movies from simulation snapshots.

## Basic Usage

1. Import your simulation images using File > Import Images or File > Import Sequence
2. Arrange your images in the desired order using the up/down buttons
3. Set your output properties like FPS and format
4. Use Preview to check how your movie will look
5. Click Create Video to generate the final output

## Features

- Support for multiple image formats
- Frame reordering
- Video preview
- Customizable output settings
- Filter effects
- Batch processing

## Keyboard Shortcuts

- Ctrl+N: New Project
- Ctrl+O: Open Project
- Ctrl+S: Save Project
- Ctrl+I: Import Images
- Delete: Remove selected items
""")
        
        text.config(state=tk.DISABLED)  # Make read-only
    
    def show_about(self):
        tk.messagebox.showinfo(
            "About SimMovieMaker",
            "SimMovieMaker v1.0\n\n"
            "A software for creating movies from simulation snapshots.\n\n"
            "Created with Python and Tkinter."
        )
    
    # Utility functions
    def on_file_select(self, event):
        self.update_selected_indices()
        
        # If a single item is selected, update the preview
        if len(self.selected_indices) == 1:
            self.current_preview_index = self.selected_indices[0]
            self.update_preview()
    
    def update_selected_indices(self):
        self.selected_indices = self.file_listbox.curselection()
    
    def update_fps(self, event):
        try:
            self.output_settings["fps"] = int(self.fps_var.get())
        except ValueError:
            # Revert to previous value
            self.fps_var.set(str(self.output_settings["fps"]))
    
    def update_format(self, event):
        self.output_settings["format"] = self.format_var.get()
    
    def update_codec(self, event):
        self.output_settings["codec"] = self.codec_var.get()


# Command-line interface for batch processing
def cli_mode():
    import argparse
    
    parser = argparse.ArgumentParser(description="SimMovieMaker - Command-line Interface")
    parser.add_argument('--input', '-i', required=True, help='Input directory or file list')
    parser.add_argument('--output', '-o', required=True, help='Output video filename')
    parser.add_argument('--fps', type=int, default=30, help='Frames per second (default: 30)')
    parser.add_argument('--format', choices=['mp4', 'avi', 'mov'], default='mp4', help='Output format (default: mp4)')
    parser.add_argument('--codec', choices=['H264', 'MJPG', 'XVID'], default='H264', help='Video codec (default: H264)')
    parser.add_argument('--pattern', help='Filename pattern for image sequence (e.g. "frame_*.png")')
    
    args = parser.parse_args()
    
    # Get input files
    input_files = []
    if os.path.isdir(args.input):
        # It's a directory, get files based on pattern
        import glob
        
        if args.pattern:
            pattern = os.path.join(args.input, args.pattern)
            input_files = sorted(glob.glob(pattern))
        else:
            # Default to common image formats
            extensions = ['*.png', '*.jpg', '*.jpeg', '*.tif', '*.tiff', '*.bmp']
            for ext in extensions:
                input_files.extend(sorted(glob.glob(os.path.join(args.input, ext))))
    else:
        # It's a file list
        with open(args.input, 'r') as f:
            input_files = [line.strip() for line in f if line.strip()]
    
    if not input_files:
        print("Error: No input files found.")
        return 1
    
    print(f"Found {len(input_files)} input files.")
    
    # Create video
    try:
        # Get first image to determine dimensions
        first_img = cv2.imread(input_files[0])
        if first_img is None:
            print(f"Error: Could not read first image: {input_files[0]}")
            return 1
            
        height, width = first_img.shape[:2]
        
        # Determine codec
        if args.format == "mp4":
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        elif args.format == "avi":
            if args.codec == "MJPG":
                fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            else:
                fourcc = cv2.VideoWriter_fourcc(*'XVID')
        elif args.format == "mov":
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        else:  # default
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        
        # Create video writer
        out = cv2.VideoWriter(args.output, fourcc, args.fps, (width, height))
        
        # Process each image
        for i, img_path in enumerate(input_files):
            print(f"Processing image {i+1}/{len(input_files)}: {os.path.basename(img_path)}")
            
            img = cv2.imread(img_path)
            if img is None:
                print(f"Warning: Could not read image: {img_path}")
                continue
                
            out.write(img)
        
        out.release()
        print(f"Video created successfully: {args.output}")
        return 0
        
    except Exception as e:
        print(f"Error creating video: {str(e)}")
        return 1


# Main function
def main():
    # Check if running in CLI mode
    if len(sys.argv) > 1:
        return cli_mode()
    
    # GUI mode
    root = tk.Tk()
    root.title("SimMovieMaker")
    
    # Ensure icon is found regardless of working directory
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smm.ico")
    if os.path.exists(icon_path):
        try:
            root.iconbitmap(icon_path)
            
            # Create a function to set icons for all dialogs
            def set_icon_for_dialog(dialog):
                try:
                    dialog.iconbitmap(icon_path)
                except Exception:
                    pass  # Silently fail if icon cannot be set
            
            # Override the Toplevel class to automatically set icons
            original_toplevel = tk.Toplevel
            class IconifiedToplevel(original_toplevel):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    set_icon_for_dialog(self)
            
            # Replace Toplevel with our custom version
            tk.Toplevel = IconifiedToplevel
            
        except tk.TclError:
            print(f"Warning: Could not load icon file '{icon_path}'")
    else:
        print(f"Warning: Icon file not found at '{icon_path}'")
    
    # Set the application icon
    try:
        root.iconbitmap("smm.ico")
    except tk.TclError:
        print("Warning: Could not load icon file 'smm.ico'")
    
    # Function to set icon for all new windows
    def set_window_icon(window):
        try:
            window.iconbitmap("smm.ico")
        except tk.TclError:
            pass  # Silently fail if icon cannot be set
    
    # Override Toplevel to automatically set icons
    original_toplevel = tk.Toplevel
    class IconifiedToplevel(original_toplevel):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            set_window_icon(self)
    
    # Replace the Toplevel class with our custom one
    tk.Toplevel = IconifiedToplevel
    
    # Set minimum size
    root.minsize(800, 600)
    
    # Create the application
    app = SimMovieMaker(root)
    
    # Start the main loop
    root.mainloop()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
