import cv2
from cv2_enumerate_cameras import enumerate_cameras
import numpy as np
import datetime
import os
import sys
import platform


def get_capture_backend():
    """Return the best cv2 capture backend for the current OS."""
    system = platform.system()
    if system == 'Windows':
        return cv2.CAP_DSHOW
    if system == 'Darwin':
        return cv2.CAP_AVFOUNDATION
    if system == 'Linux':
        return cv2.CAP_V4L2
    return cv2.CAP_ANY

HELP_TEXT = '''\
Boson 320+ Terminal Streamer

Commands:
    help           Show this help message and list all commands
    list           List available camera devices
    stream         Show video stream only, does NOT save data
    record         Start video stream and record video/raw data
    view           Play back a recorded video file with controls

Usage:
    python boson_stream.py help
    python boson_stream.py list
    python boson_stream.py stream <camera_index>
    python boson_stream.py record [manual_filename] <camera_index> [-n NUM_FRAMES]
    python boson_stream.py view <path/to/file>

Options:
    -n NUM_FRAMES  Number of frames to record (stops automatically).
                   If omitted, records until 'q' is pressed.

View controls:
    c              Pause / resume playback
    z              Step back 1 frame (while paused)
    x              Step forward 1 frame (while paused)
    q              Quit viewer

Files saved in ./data/<manual_filename> folder:
    - Video (.avi)
    - Raw data (.npy)
    - CSV (.csv, first frame)
'''

def show_help():
    print(HELP_TEXT)

def list_cameras():
    print('Listing available camera devices...')
    cameras = enumerate_cameras(get_capture_backend())
    if not cameras:
        print('  No cameras found.')
        return
    for cam in cameras:
        print(f'  Camera index {cam.index}: {cam.name}')


def get_timestamp():
    return datetime.datetime.now().strftime('%Y%m%d_%H%M%S')

def sanitize_filename(name):
    return name.replace(' ', '_').replace('.', '_')

def parse_record_args(has_filename):
    """Parse record subcommand args: record [filename] <camera_index> [-n num_frames]"""
    camera_index = 0
    num_frames = None
    start = 3 if has_filename else 2
    args = sys.argv[start:]
    i = 0
    while i < len(args):
        if args[i] == '-n':
            if i + 1 < len(args):
                try:
                    num_frames = int(args[i + 1])
                    if num_frames <= 0:
                        print('Number of frames must be positive. Recording indefinitely.')
                        num_frames = None
                except ValueError:
                    print('Invalid value for -n. Recording indefinitely.')
                i += 2
            else:
                print('Missing value for -n. Recording indefinitely.')
                i += 1
        else:
            try:
                camera_index = int(args[i])
            except ValueError:
                print('Invalid camera index. Using default (0).')
            i += 1
    return camera_index, num_frames

def record_stream(manual_filename, has_filename=True):
    camera_index, num_frames = parse_record_args(has_filename)

    cap = cv2.VideoCapture(camera_index, get_capture_backend())
    if not cap.isOpened():
        print(f'Error: Could not open camera at index {camera_index}.')
        return

    base_filename = sanitize_filename(manual_filename)
    timestamp = get_timestamp()
    file_prefix = f'{base_filename}_{timestamp}' if has_filename else timestamp
    out_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', base_filename)
    os.makedirs(out_folder, exist_ok=True)

    # VideoWriter setup
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    video_filename = f'{file_prefix}.avi'
    video_filepath = os.path.join(out_folder, video_filename)
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = int(cap.get(cv2.CAP_PROP_FPS)) or 30
    out_video = cv2.VideoWriter(video_filepath, fourcc, fps, (frame_width, frame_height))

    # Raw data storage
    raw_data = []

    if num_frames:
        print(f'Recording {num_frames} frames from camera index {camera_index}. Press "q" to stop early.')
    else:
        print(f'Press "q" to stop recording. Using camera index {camera_index}.')
    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            print('Error: Failed to read frame.')
            break

        cv2.imshow('Boson 320+ Stream', frame)
        out_video.write(frame)

        # Store raw data (convert to 16-bit if needed)
        if frame.dtype != np.uint16:
            frame16 = np.left_shift(frame.astype(np.uint16), 8)
        else:
            frame16 = frame
        raw_data.append(frame16)
        frame_count += 1

        if num_frames and frame_count >= num_frames:
            print(f'Captured {frame_count} frames.')
            break

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    out_video.release()
    cv2.destroyAllWindows()

    # Save raw data as .npy file
    npy_filename = f'{file_prefix}_raw.npy'
    npy_filepath = os.path.join(out_folder, npy_filename)
    raw_array = np.array(raw_data)
    np.save(npy_filepath, raw_array)

    # Save raw data as CSV (first frame only for demo, can be expanded)
    csv_filename = f'{file_prefix}_raw_frame0.csv'
    csv_filepath = os.path.join(out_folder, csv_filename)
    # If frames are multi-channel, flatten to 2D for CSV
    if raw_array.ndim == 4:
        # Save only first frame, all channels
        np.savetxt(csv_filepath, raw_array[0].reshape(-1, raw_array.shape[-1]), delimiter=',', fmt='%d')
    else:
        np.savetxt(csv_filepath, raw_array[0], delimiter=',', fmt='%d')

    print(f'''Recording stopped. 
        Video saved to: {video_filepath}
        Raw data saved to: {npy_filepath}
        CSV saved to: {csv_filepath}''')

def load_frames(filepath):
    """Load frames from .npy or video file. Returns list of BGR frames."""
    if filepath.endswith('.npy'):
        raw = np.load(filepath)
        frames = []
        for i in range(raw.shape[0]):
            f = raw[i]
            # Normalize to 8-bit for display
            if f.dtype != np.uint8:
                f = (f / f.max() * 255).astype(np.uint8) if f.max() > 0 else f.astype(np.uint8)
            # Convert grayscale to BGR
            if f.ndim == 2:
                f = cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)
            frames.append(f)
        return frames

    cap = cv2.VideoCapture(filepath)
    if not cap.isOpened():
        return None
    frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    cap.release()
    return frames

def view_video(filepath):
    if filepath.endswith('.csv'):
        print('CSV playback not supported. Please provide a .npy or video file.')
        return
    
    cap = cv2.VideoCapture(filepath)
    frames = load_frames(filepath)
    if not frames:
        print(f'Error: Could not load any frames from "{filepath}".')
        return

    total_frames = len(frames)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    delay = int(1000 / fps)

    window_name = f'View: {os.path.basename(filepath)}'
    cv2.namedWindow(window_name)

    paused = False
    current_frame = 0

    def on_trackbar(pos):
        nonlocal current_frame
        current_frame = pos

    cv2.createTrackbar('Frame', window_name, 0, total_frames - 1, on_trackbar)

    print(f'Playing {filepath} ({total_frames} frames, {fps} fps)')
    print('c: pause/play | z: prev frame | x: next frame | q: quit')

    while True:
        cv2.imshow(window_name, frames[current_frame])
        cv2.setTrackbarPos('Frame', window_name, current_frame)

        key = cv2.waitKey(delay if not paused else 30) & 0xFF

        if key == ord('q'):
            break
        elif key == ord('c'):
            paused = not paused
        elif key == ord('z'):
            paused = True
            current_frame = max(current_frame - 1, 0)
        elif key == ord('x'):
            paused = True
            current_frame = min(current_frame + 1, total_frames - 1)

        if not paused:
            current_frame = (current_frame + 1) % total_frames

    cv2.destroyAllWindows()
    print('Viewer closed.')

def main():
    if len(sys.argv) < 2:
        show_help()
        return
    cmd = sys.argv[1].lower()
    if cmd == 'help':
        show_help()
    elif cmd == 'list':
        list_cameras()
    elif cmd == 'stream':
        camera_index = 0
        if len(sys.argv) > 2:
            try:
                camera_index = int(sys.argv[2])
            except ValueError:
                print('Invalid camera index. Using default (0).')
        cap = cv2.VideoCapture(camera_index, get_capture_backend())
        if not cap.isOpened():
            print(f'Error: Could not open camera at index {camera_index}.')
            return
        print(f'Press "q" to stop streaming. Using camera index {camera_index}.')
        while True:
            ret, frame = cap.read()
            if not ret:
                print('Error: Failed to read frame.')
                break
            cv2.imshow('Boson 320+ Stream', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        cap.release()
        cv2.destroyAllWindows()
        print('Stream stopped.')
    elif cmd == 'view':
        if len(sys.argv) < 3:
            print('Usage: python boson_stream.py view <filename>')
            return
        view_video(sys.argv[2])
    elif cmd == 'record':
        has_filename = len(sys.argv) > 2 and sys.argv[2] not in ('-n',) and not sys.argv[2].isdigit()
        manual_filename = sys.argv[2] if has_filename else get_timestamp()
        record_stream(manual_filename, has_filename)
    else:
        print('Unknown command.')
        show_help()

if __name__ == '__main__':
    main()
