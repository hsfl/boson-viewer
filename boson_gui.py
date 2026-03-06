import sys
import os
import datetime
import platform
import threading
import cv2
import numpy as np
from cv2_enumerate_cameras import enumerate_cameras

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QDialog, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QFileDialog, QSpinBox, QListWidget,
    QDialogButtonBox, QMessageBox, QSizePolicy, QSlider, QLineEdit,
    QRadioButton, QAbstractItemView,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QImage, QPixmap


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_capture_backend():
    s = platform.system()
    if s == 'Windows':  return cv2.CAP_DSHOW
    if s == 'Darwin':   return cv2.CAP_AVFOUNDATION
    if s == 'Linux':    return cv2.CAP_V4L2
    return cv2.CAP_ANY

def get_timestamp():
    return datetime.datetime.now().strftime('%Y%m%d_%H%M%S')

def sanitize(name):
    return name.replace(' ', '_').replace('.', '_')

def data_dir():
    if getattr(sys, 'frozen', False):
        return os.path.expanduser('~/Boson Viewer/data')
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

def frame_to_pixmap(frame, label_size):
    """Convert a BGR numpy frame to a QPixmap scaled to fit label_size."""
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
    return QPixmap.fromImage(img).scaled(
        label_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


# ── Camera Thread ──────────────────────────────────────────────────────────────

class CameraThread(QThread):
    frame_ready     = pyqtSignal(np.ndarray)
    recording_done  = pyqtSignal(str, str, str)   # video, npy, csv paths
    error           = pyqtSignal(str)

    def __init__(self, camera_index):
        super().__init__()
        self.camera_index = camera_index
        self._running = False

        # recording state – guarded by _lock
        self._lock        = threading.Lock()
        self._recording   = False
        self._out_video   = None
        self._raw_data    = []
        self._frame_count = 0
        self._frame_limit = None
        self._video_path  = None
        self._out_folder  = None
        self._file_prefix = None

        # set in run() once camera opens
        self.frame_width  = 640
        self.frame_height = 480
        self.fps          = 30

    # ── public API (called from main thread) ───────────────────────────────────

    def start_recording(self, out_folder, file_prefix, num_frames):
        """Begin recording. num_frames < 1 means record until stop_recording()."""
        video_path = os.path.join(out_folder, f'{file_prefix}.avi')
        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        out_video = cv2.VideoWriter(
            video_path, fourcc, self.fps,
            (self.frame_width, self.frame_height))

        with self._lock:
            self._out_folder  = out_folder
            self._file_prefix = file_prefix
            self._video_path  = video_path
            self._out_video   = out_video
            self._raw_data    = []
            self._frame_count = 0
            self._frame_limit = num_frames if (num_frames and num_frames > 0) else None
            self._recording   = True

    def stop_recording(self):
        """Stop recording and persist files. Safe to call from any thread."""
        with self._lock:
            if not self._recording:
                return
            self._recording  = False
            out_video        = self._out_video
            self._out_video  = None
            raw_snapshot     = self._raw_data[:]
            self._raw_data   = []
            video_path       = self._video_path
            out_folder       = self._out_folder
            file_prefix      = self._file_prefix

        if out_video:
            out_video.release()
        self._persist(raw_snapshot, video_path, out_folder, file_prefix)

    def stop(self):
        self._running = False
        self.wait()

    # ── internal ───────────────────────────────────────────────────────────────

    def _persist(self, raw_data, video_path, out_folder, file_prefix):
        if not raw_data:
            self.recording_done.emit(video_path or '', '', '')
            return
        raw_array = np.array(raw_data)
        npy_path  = os.path.join(out_folder, f'{file_prefix}_raw.npy')
        csv_path  = os.path.join(out_folder, f'{file_prefix}_raw_frame0.csv')
        np.save(npy_path, raw_array)
        if raw_array.ndim == 4:
            np.savetxt(csv_path,
                       raw_array[0].reshape(-1, raw_array.shape[-1]),
                       delimiter=',', fmt='%d')
        else:
            np.savetxt(csv_path, raw_array[0], delimiter=',', fmt='%d')
        self.recording_done.emit(video_path, npy_path, csv_path)

    def run(self):
        self._running = True
        cap = cv2.VideoCapture(self.camera_index, get_capture_backend())
        if not cap.isOpened():
            self.error.emit(f'Could not open camera {self.camera_index}.')
            return

        self.frame_width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))  or 640
        self.frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
        self.fps          = int(cap.get(cv2.CAP_PROP_FPS))          or 30

        while self._running:
            ret, frame = cap.read()
            if not ret:
                self.error.emit('Failed to read frame from camera.')
                break

            self.frame_ready.emit(frame.copy())

            limit_reached = False
            with self._lock:
                if self._recording and self._out_video:
                    self._out_video.write(frame)
                    f16 = (np.left_shift(frame.astype(np.uint16), 8)
                           if frame.dtype != np.uint16 else frame)
                    self._raw_data.append(f16)
                    self._frame_count += 1
                    if (self._frame_limit and
                            self._frame_count >= self._frame_limit):
                        limit_reached = True

            if limit_reached:
                self.stop_recording()

        cap.release()


# ── Startup Dialogs ────────────────────────────────────────────────────────────

class CameraSelectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Select Camera')
        self.setMinimumWidth(420)
        self.selected_index = None
        self._cameras = []

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        header.addWidget(QLabel('Choose a camera to use:'))
        scan_btn = QPushButton('Scan')
        scan_btn.setFixedWidth(70)
        scan_btn.clicked.connect(self._scan)
        header.addWidget(scan_btn)
        layout.addLayout(header)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._scan()

    def _scan(self):
        self.list_widget.clear()
        self._cameras = enumerate_cameras(get_capture_backend())
        if self._cameras:
            for cam in self._cameras:
                self.list_widget.addItem(f'[{cam.index}]  {cam.name}')
            self.list_widget.setCurrentRow(0)
        else:
            self.list_widget.addItem('No cameras found.')

    def _accept(self):
        row = self.list_widget.currentRow()
        if self._cameras and 0 <= row < len(self._cameras):
            self.selected_index = self._cameras[row].index
            self.accept()
        else:
            QMessageBox.warning(self, 'No camera', 'No camera available to select.')


class FolderSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Select Save Folder')
        self.setMinimumWidth(480)
        self.folder_path = None
        self._existing = None

        layout = QVBoxLayout(self)

        # existing folder option
        self.radio_existing = QRadioButton('Open existing folder')
        self.radio_existing.setChecked(True)
        layout.addWidget(self.radio_existing)

        self._existing_widget = QWidget()
        row = QHBoxLayout(self._existing_widget)
        row.setContentsMargins(20, 0, 0, 0)
        self._existing_label = QLabel('No folder selected')
        self._existing_label.setStyleSheet('color: gray;')
        browse_btn = QPushButton('Browse…')
        browse_btn.clicked.connect(self._browse)
        row.addWidget(self._existing_label, 1)
        row.addWidget(browse_btn)
        layout.addWidget(self._existing_widget)

        # new folder option
        self.radio_new = QRadioButton('Create new folder')
        layout.addWidget(self.radio_new)

        self._new_widget = QWidget()
        self._new_widget.setEnabled(False)
        row2 = QHBoxLayout(self._new_widget)
        row2.setContentsMargins(20, 0, 0, 0)
        row2.addWidget(QLabel('Name:'))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText('e.g. experiment_01')
        row2.addWidget(self._name_edit, 1)
        layout.addWidget(self._new_widget)

        hint = QLabel(f'Will be created inside:  {data_dir()}/')
        hint.setStyleSheet('color: gray; font-size: 11px;')
        hint.setContentsMargins(20, 0, 0, 8)
        layout.addWidget(hint)

        self.radio_existing.toggled.connect(self._toggle)
        self.radio_new.toggled.connect(self._toggle)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _toggle(self):
        use_existing = self.radio_existing.isChecked()
        self._existing_widget.setEnabled(use_existing)
        self._new_widget.setEnabled(not use_existing)

    def _browse(self):
        start = os.path.expanduser('~/Boson Viewer/data')
        os.makedirs(start, exist_ok=True)
        folder = QFileDialog.getExistingDirectory(self, 'Select Folder', start)
        if folder:
            self._existing = folder
            self._existing_label.setText(folder)
            self._existing_label.setStyleSheet('')

    def _accept(self):
        if self.radio_existing.isChecked():
            if not self._existing:
                QMessageBox.warning(self, 'No folder', 'Please select a folder.')
                return
            self.folder_path = self._existing
        else:
            name = self._name_edit.text().strip()
            if not name:
                QMessageBox.warning(self, 'No name', 'Please enter a folder name.')
                return
            self.folder_path = os.path.join(data_dir(), sanitize(name))
            os.makedirs(self.folder_path, exist_ok=True)
        self.accept()


# ── File Browser + Viewer ──────────────────────────────────────────────────────

class FileListDialog(QDialog):
    """Lists .avi / .npy files in a folder; user picks one to view."""

    def __init__(self, folder_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Data — {os.path.basename(folder_path)}')
        self.setMinimumSize(500, 340)
        self.selected_file = None
        self._files = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(folder_path))

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SingleSelection)

        for f in sorted(os.listdir(folder_path)):
            if f.endswith('.avi') or f.endswith('.npy'):
                self._files.append(os.path.join(folder_path, f))
                self.list_widget.addItem(f)

        if not self._files:
            self.list_widget.addItem('No .avi or .npy files found.')

        self.list_widget.itemDoubleClicked.connect(self._open)
        layout.addWidget(self.list_widget)

        btns = QDialogButtonBox(QDialogButtonBox.Open | QDialogButtonBox.Close)
        btns.accepted.connect(self._open)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _open(self):
        row = self.list_widget.currentRow()
        if self._files and 0 <= row < len(self._files):
            self.selected_file = self._files[row]
            self.accept()


def _load_frames(filepath):
    """Return (list[bgr_frame], fps)."""
    if filepath.endswith('.npy'):
        raw = np.load(filepath)
        frames = []
        for i in range(raw.shape[0]):
            f = raw[i]
            if f.dtype != np.uint8:
                mx = f.max()
                f = ((f / mx) * 255).astype(np.uint8) if mx > 0 else f.astype(np.uint8)
            if f.ndim == 2:
                f = cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)
            frames.append(f)
        return frames, 30.0

    cap = cv2.VideoCapture(filepath)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    cap.release()
    return frames, fps


class ViewerDialog(QDialog):
    def __init__(self, filepath, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Viewer — {os.path.basename(filepath)}')
        self.setMinimumSize(700, 560)
        self.setAttribute(Qt.WA_DeleteOnClose)

        frames, fps = _load_frames(filepath)
        self._frames = frames
        self._total  = len(frames)
        self._cur    = 0
        self._paused = False
        self._delay  = max(1, int(1000 / fps))

        layout = QVBoxLayout(self)

        # video display
        self._video_lbl = QLabel()
        self._video_lbl.setAlignment(Qt.AlignCenter)
        self._video_lbl.setStyleSheet('background: black;')
        self._video_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._video_lbl, 1)

        # scrubber
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, max(0, self._total - 1))
        self._slider.sliderMoved.connect(self._seek)
        layout.addWidget(self._slider)

        # frame counter
        self._counter = QLabel()
        self._counter.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._counter)

        # controls
        ctrl = QHBoxLayout()
        prev_btn = QPushButton('◀ Prev')
        prev_btn.clicked.connect(self._prev)
        self._play_btn = QPushButton('Pause')
        self._play_btn.clicked.connect(self._toggle_play)
        next_btn = QPushButton('Next ▶')
        next_btn.clicked.connect(self._next)
        for b in (prev_btn, self._play_btn, next_btn):
            ctrl.addWidget(b)
        layout.addLayout(ctrl)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        if self._total > 0:
            self._show(0)
            self._timer.start(self._delay)

    def _show(self, idx):
        if not self._frames or not (0 <= idx < self._total):
            return
        self._cur = idx
        self._video_lbl.setPixmap(
            frame_to_pixmap(self._frames[idx], self._video_lbl.size()))
        self._slider.setValue(idx)
        self._counter.setText(f'Frame {idx + 1} / {self._total}')

    def _advance(self):
        if not self._paused:
            self._show((self._cur + 1) % self._total)

    def _toggle_play(self):
        self._paused = not self._paused
        self._play_btn.setText('Play' if self._paused else 'Pause')

    def _prev(self):
        self._paused = True
        self._play_btn.setText('Play')
        self._show(max(0, self._cur - 1))

    def _next(self):
        self._paused = True
        self._play_btn.setText('Play')
        self._show(min(self._total - 1, self._cur + 1))

    def _seek(self, pos):
        self._paused = True
        self._play_btn.setText('Play')
        self._show(pos)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._show(self._cur)

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)


# ── Main Window ────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self, camera_index, folder_path):
        super().__init__()
        self.camera_index = camera_index
        self.folder_path  = folder_path
        self._recording   = False

        self._build_ui()
        self._start_camera()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        self._refresh_title()
        self.setMinimumSize(860, 680)

        root = QWidget()
        self.setCentralWidget(root)
        vbox = QVBoxLayout(root)
        vbox.setSpacing(8)
        vbox.setContentsMargins(12, 10, 12, 12)

        # top bar: folder path + change folder button
        top = QHBoxLayout()
        self._folder_lbl = QLabel()
        self._folder_lbl.setStyleSheet('color: gray; font-size: 11px;')
        self._set_folder_label()
        top.addWidget(self._folder_lbl, 1)
        change_btn = QPushButton('Change Folder')
        change_btn.clicked.connect(self._change_folder)
        top.addWidget(change_btn)
        vbox.addLayout(top)

        # status line (shows last save info)
        self._status_lbl = QLabel('')
        self._status_lbl.setStyleSheet('color: #555; font-size: 11px;')
        self._status_lbl.setAlignment(Qt.AlignCenter)
        vbox.addWidget(self._status_lbl)

        # live stream (fills remaining space)
        self._video_lbl = QLabel('Connecting to camera…')
        self._video_lbl.setAlignment(Qt.AlignCenter)
        self._video_lbl.setStyleSheet('background: black; color: #666; font-size: 16px;')
        self._video_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        vbox.addWidget(self._video_lbl, 1)

        # bottom bar
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 4, 0, 0)

        # bottom-left: View Data
        view_btn = QPushButton('View Data')
        view_btn.setFixedWidth(120)
        view_btn.setToolTip('Browse and play back .avi or .npy files in the save folder')
        view_btn.clicked.connect(self._view_data)
        bottom.addWidget(view_btn, 0, Qt.AlignLeft | Qt.AlignVCenter)

        bottom.addStretch(1)

        # bottom-center: Record / Stop
        self._rec_btn = QPushButton('Start Recording')
        self._rec_btn.setMinimumWidth(220)
        self._rec_btn.setFixedHeight(54)
        f = self._rec_btn.font()
        f.setPointSize(15)
        f.setBold(True)
        self._rec_btn.setFont(f)
        self._set_rec_btn_style(recording=False)
        self._rec_btn.clicked.connect(self._toggle_recording)
        bottom.addWidget(self._rec_btn, 0, Qt.AlignCenter | Qt.AlignVCenter)

        bottom.addStretch(1)

        # bottom-right: Frames spinbox
        frames_col = QVBoxLayout()
        frames_col.setSpacing(2)
        lbl = QLabel('Frames')
        lbl.setAlignment(Qt.AlignCenter)
        self._frames_spin = QSpinBox()
        self._frames_spin.setRange(-1, 999_999)
        self._frames_spin.setValue(-1)
        self._frames_spin.setSpecialValueText('∞  Indefinite')
        self._frames_spin.setToolTip(
            'Frames to record. -1 = record until Stop is clicked.')
        self._frames_spin.setFixedWidth(140)
        frames_col.addWidget(lbl)
        frames_col.addWidget(self._frames_spin)
        bottom.addLayout(frames_col)

        vbox.addLayout(bottom)

    def _set_folder_label(self):
        self._folder_lbl.setText(f'Save folder:  {self.folder_path}')

    def _refresh_title(self):
        self.setWindowTitle(os.path.basename(self.folder_path))

    def _set_rec_btn_style(self, recording):
        if recording:
            self._rec_btn.setText('Stop Recording')
            self._rec_btn.setStyleSheet(
                'background-color: #c62828; color: white; border-radius: 6px;')
        else:
            self._rec_btn.setText('Start Recording')
            self._rec_btn.setStyleSheet(
                'background-color: #2e7d32; color: white; border-radius: 6px;')

    # ── camera ────────────────────────────────────────────────────────────────

    def _start_camera(self):
        self._cam = CameraThread(self.camera_index)
        self._cam.frame_ready.connect(self._on_frame)
        self._cam.recording_done.connect(self._on_recording_done)
        self._cam.error.connect(self._on_error)
        self._cam.start()

    def _on_frame(self, frame):
        self._video_lbl.setPixmap(
            frame_to_pixmap(frame, self._video_lbl.size()))

    # ── recording ─────────────────────────────────────────────────────────────

    def _toggle_recording(self):
        if self._recording:
            self._cam.stop_recording()
        else:
            num_frames = self._frames_spin.value()   # -1 → indefinite
            timestamp  = get_timestamp()
            prefix     = f'{sanitize(os.path.basename(self.folder_path))}_{timestamp}'

            self._cam.start_recording(self.folder_path, prefix, num_frames)
            self._recording = True
            self._set_rec_btn_style(recording=True)
            self._frames_spin.setEnabled(False)
            desc = f'{num_frames} frames' if num_frames > 0 else 'indefinitely'
            self._status_lbl.setText(f'Recording {desc}…')

    def _on_recording_done(self, video_path, npy_path, csv_path):
        self._recording = False
        self._set_rec_btn_style(recording=False)
        self._frames_spin.setEnabled(True)
        if video_path:
            self._status_lbl.setText(
                f'Saved:  {os.path.basename(video_path)}'
                f'  |  {os.path.basename(npy_path)}'
                f'  |  {os.path.basename(csv_path)}')
        else:
            self._status_lbl.setText('Recording stopped — no frames captured.')

    def _on_error(self, msg):
        QMessageBox.critical(self, 'Camera Error', msg)

    # ── folder change ─────────────────────────────────────────────────────────

    def _change_folder(self):
        dlg = FolderSetupDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            if self._recording:
                self._cam.stop_recording()
            self.folder_path = dlg.folder_path
            self._set_folder_label()
            self._refresh_title()
            self._status_lbl.setText('')

    # ── viewer ────────────────────────────────────────────────────────────────

    def _view_data(self):
        file_dlg = FileListDialog(self.folder_path, self)
        if file_dlg.exec_() == QDialog.Accepted and file_dlg.selected_file:
            ViewerDialog(file_dlg.selected_file, self).exec_()

    # ── cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._recording:
            self._cam.stop_recording()
        self._cam.stop()
        super().closeEvent(event)


# ── Entry Point ────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    # 1. Select camera
    cam_dlg = CameraSelectDialog()
    if cam_dlg.exec_() != QDialog.Accepted or cam_dlg.selected_index is None:
        sys.exit(0)

    # 2. Select / create save folder
    folder_dlg = FolderSetupDialog()
    if folder_dlg.exec_() != QDialog.Accepted or not folder_dlg.folder_path:
        sys.exit(0)

    # 3. Launch main window
    win = MainWindow(cam_dlg.selected_index, folder_dlg.folder_path)
    win.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
