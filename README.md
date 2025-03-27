# SimMovieMaker 
![image](https://github.com/user-attachments/assets/31a631e7-9c5b-4fd5-8f0b-bf4d554804be)

Installation and Usage Guide

## Installation Requirements

### Prerequisites
- Python 3.7 or higher
- pip (Python package installer)

### Required Libraries
- OpenCV (cv2)
- NumPy
- Pillow (PIL)
- tkinter (usually included with Python)

## Installation Steps

1. **Clone or download the code**
   Save the SimMovieMaker.py file to your local machine.

2. **Install required dependencies**
   Open a terminal/command prompt and run:
   ```
   pip install opencv-python numpy pillow
   ```

3. **Run the application**
   Navigate to the directory containing SimMovieMaker.py and run:
   ```
   python SimMovieMaker.py
   ```

## Basic Usage

### Creating a Movie from Simulation Snapshots

1. **Import Images**
   - Click on **File → Import Images** to select individual image files
   - Click on **File → Import Sequence** to import a numbered sequence of images from a directory

2. **Arrange Images**
   - Select an image in the list and use the ↑/↓ buttons to change its position
   - Use **Edit → Select All** to select all images
   - Use **Edit → Delete Selected** to remove unwanted images

3. **Preview**
   - Navigate through images using the preview controls at the bottom
   - Click **Preview Video** to generate a temporary preview of your movie

4. **Adjust Settings**
   - Set the frames per second (FPS) in the Properties panel
   - Select output format (mp4, avi, mov)
   - Choose video codec (H264, MJPG, XVID)

5. **Create Video**
   - Click the **Create Video** button
   - Choose the output location and filename
   - Wait for the encoding process to complete

## Advanced Features

### Video Filters

Access filters through the **Filters** menu:

- **Adjust Size**: Crop, resize, or rotate images
- **Adjust Colors**: Modify brightness, contrast, or apply color effects
- **Overlay**: Add text, scale bars, or timestamps to your images

### Batch Processing

For large simulation datasets, you can use the command-line interface:

```
python SimMovieMaker.py --input /path/to/images --output output.mp4 --fps 30 --pattern "frame_*.png"
```

Command-line parameters:
- `--input, -i`: Directory containing images or a text file with image paths
- `--output, -o`: Output video filename
- `--fps`: Frames per second (default: 30)
- `--format`: Output format (mp4, avi, mov)
- `--codec`: Video codec (H264, MJPG, XVID)
- `--pattern`: Filename pattern for image sequence

### Project Management

- **File → Save Project**: Save your current work to continue later
- **File → Open Project**: Resume work on a previously saved project
- **Tools → Export File List**: Export a list of the current images
- **Tools → Import File List**: Import a previously exported list

## Troubleshooting

- **Video creation fails**: Check that all images have the same dimensions
- **Images don't appear in the preview**: Verify that the file format is supported
- **Poor video quality**: Try adjusting the codec or quality settings

## Need Help?

- Access the built-in documentation via **Help → Documentation**
- View information about the software via **Help → About**
