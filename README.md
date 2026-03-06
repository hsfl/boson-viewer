# Boson Thermal Camera Viewer

Cross-platform terminal-based tool for the FLIR Boson 320+ thermal camera. Supports live streaming and video capture with raw data export.

## Files
- `boson_stream.py` — CLI tool for camera streaming and recording
- `boson_gui.py` — GUI application for camera streaming and recording
- `requirements.txt` — Python dependencies

## Installation
1. Download this repo from Github

2. setup a python virtual environment in the project folder
```bash
python -m venv .venv
```

3. activate your virtual environment. you'll know it's activated if you see (.venv) followed by your username.
```bash
# for Linux/macOS:
source .venv/bin/activate

# for Windows:
.venv/Scripts/activate.ps1
```

4. install python dependencies
```bash
pip install -r requirements.txt
```

## GUI Application (`boson_gui.py`)

A point-and-click interface for the Boson camera. On launch it prompts you to select a camera and a save folder, then opens a window with a live stream, record button, and data viewer.

### Running the GUI directly
```bash
python boson_gui.py
```

Data is saved to `./data/` (relative to the script) when run this way.

### Building an executable

The GUI can be compiled into a standalone `Boson Viewer.app` that lives on your Desktop and requires no terminal to use. Run this once from the project folder with your virtual environment activated:

```bash
# on Linux/macOS
pyinstaller -y --distpath ~/Desktop boson_gui.spec

# on Windows
pyinstaller -y --distpath %USERPROFILE%\Desktop boson_gui.spec
```

This places `Boson Viewer.app` on your Desktop. When launched as an app, data is saved to `~/Boson Viewer/data/` by default (the folder is created automatically).

> **First launch on macOS:** if you see "unidentified developer", right-click the app → Open → Open to allow it once.

To rebuild after editing `boson_gui.py`, run the same `pyinstaller` command again (the old `.app` will be replaced).

## Usage
1. run `source .venv/bin/activate` if not already activated.
> IMPORTANT: make sure (.venv) is activated before running any commands!!

### Commands
1. `help`: To view a help menu with a list of available commands
```bash
python boson_stream.py help
```

2. `list`: To list available camera devices:
```bash
python boson_stream.py list
```

sample output (on macOS):
```
Listing available camera devices...
  Camera index 0: FLIR Camera
  Camera index 1: FaceTime HD Camera
```
> Depending on your device, the Boson camera will be named differently. Generally, you'll see something like "FLIR Camera" or "Boson Video"

3. `stream`: to view the video stream only. if `camera_index` is not specified, the camera at index 0 will be selected by default.
```bash
python boson_stream.py stream [camera_index]
```
This will pop up a window with a live stream from the camera. TO END STREAMING: click on the window and press `q`.
> note: this command does NOT save any data.

4. `record`: to record videos and save raw data in `./data/<filename>/`. if `filename` is not specified, it will save to a folder with the current timestamp in `./data/`. if the `camera_index` is not specified, the camera at index 0 will be selected by default. if `-n NUM_FRAMES` is not specified, it will record indefinitely until you click on the window and press `q` to stop.
```bash
python boson_stream.py record [filename] [camera_index] [-n NUM_FRAMES]
```
> WARNING: do NOT click X or use Ctrl+C to close the window. This will NOT save the files!!!

> generally as a good practice, run the list and stream commands first before recording. this ensures that the camera is properly connected and you are using the correct index. also good practice to specify the number of frames to avoid very very large files!

examples:
```bash
# to save data to folder ./data/test, using camera at index 2, recording 100 frames
python boson_stream.py record test 2 -n 100

# to save data to folder ./data/<timestamp>, using camera at index 2, recording 100 frames
python boson_stream.py record 2 -n 100

# to save data to folder ./data/<timestamp>, using camera at index 0, recording 100 frames
python boson_stream.py record -n 100

# to save data to folder ./data/<timestamp>, using camera at index 0, recording until I press 'q'
python boson_stream.py record
```

After recording ends, the terminal will output the location of your files.
```bash
Recording 100 frames from camera index 0. Press "q" to stop early.

Captured 100 frames.
Recording stopped. 
        Video saved to: /Users/samanthamallari/Desktop/boson-viewer/data/20260305_154028/20260305_154028.avi
        Raw data saved to: /Users/samanthamallari/Desktop/boson-viewer/data/20260305_154028/20260305_154028_raw.npy
        CSV saved to: /Users/samanthamallari/Desktop/boson-viewer/data/20260305_154028/20260305_154028_raw_frame0.csv
```

5. `view`: to view a playback of a previously recording .avi or .npy file. to exit, click on the window and press `q`.
```bash
python boson_stream.py view <path/to/file>
```
> currently, CSV is not suppported by the playback viewer. 

examples:
```bash
python boson_stream.py data/20260305_154028/20260305_154028.avi

python boson_stream.py data/20260305_154028/20260305_154028_raw.npy
```

### View Controls

- `c` — pause / resume playback
- `z` — go back 1 frame (while paused)
- `x` — go forward 1 frame (while paused)
- Trackbar — scrub to any frame
- `q` — quit viewer

## Saved File Format

Files are saved into `./data/<filename>/`:

```
data/<filename>/
    <filename>_<YYYYMMDD_HHMMSS>.avi                # video recording
    <filename>_<YYYYMMDD_HHMMSS>_raw.npy            # raw data (full bit depth)
    <filename>_<YYYYMMDD_HHMMSS>_raw_frame0.csv     # raw data as CSV (first frame only)
```

If a filename is not specified,
```
data/<YYYYMMDD_HHMMSS>/
    <YYYYMMDD_HHMMSS>.avi                # video recording
    <YYYYMMDD_HHMMSS>_raw.npy            # raw data (full bit depth)
    <YYYYMMDD_HHMMSS>_raw_frame0.csv     # raw data as CSV (first frame only)
```