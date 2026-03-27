# -*- coding: utf-8 -*-
"""
PySide6 음악 플레이어

구현 기능
- 메뉴바 없음
- 트레이 아이콘
  - 더블클릭: 창 표시
  - 우클릭: 재생 / 일시정지 / 정지 / 이전곡 / 다음곡 / 종료
- 재생 컨트롤
  - 이전곡 / 재생 / 일시정지 / 정지 / 다음곡
- 볼륨 슬라이더
- 현재 진행 슬라이더
- 재생 목록 테이블
  - 더블클릭 재생
  - 우클릭 메뉴: 폴더 열기 / 태그 편집 / 삭제
- 재생 모드
  - 한곡 반복재생
  - 전체 반복재생
  - 체크항목 반복재생
  - 전체 랜덤재생
  - 체크항목 랜덤재생
- 체크박스 기반 재생 대상 제어
- A/B 구간반복
  - A 시작 슬라이더
  - B 끝 슬라이더
  - 현재 위치 -> A / 현재 위치 -> B
  - A-B 반복 ON/OFF
- 단축키 (프로그램 활성 상태일 때만 동작)
  - Space: 재생/일시정지 토글
  - Left : 5초 뒤로
  - Right: 5초 앞으로
- 단일 인스턴스
  - 이미 실행 중일 때 음악 파일을 다시 열면
    기존 실행본의 재생목록 끝에 추가 후 즉시 재생
- 재생목록 저장/복원
- 설정 저장/복원
- 태그 읽기/편집
  - title / artist / album

주의
- "기본 플레이어 연결" 자체는 운영체제나 설치 프로그램에서 해야 한다.
- 이 코드는 "이미 기본 앱으로 연결되어 있을 때", 탐색기 더블클릭으로 전달된 파일 경로를 처리한다.
"""

from __future__ import annotations

import json
import os
import random
import sys
from dataclasses import dataclass, asdict
from enum import Enum, auto
from typing import Any, List, Optional

from mutagen._file import File as MutagenFile

from PySide6.QtCore import Qt, QObject, Signal, QUrl, QPoint, QSize, QRect, QTimer
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QIcon,
    QPainter,
    QPixmap,
    QShortcut,
    QKeySequence,
)
from PySide6.QtMultimedia import QMediaDevices, QAudioDevice, QAudioOutput, QMediaPlayer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
    QPushButton,
    QMainWindow,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QComboBox,
    QLabel,
    QSlider,
    QMessageBox,
    QSystemTrayIcon,
    QMenu,
    QStyle,
    QAbstractItemView,
    QLineEdit,
    QCheckBox,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QFontComboBox,
    QSpinBox,
    QStyledItemDelegate,
    QStyleOptionButton,
    QTabWidget,
    QToolButton,
)


APP_NAME = "SimpleMusicPlayer"
APP_ORG = "local"
LOCAL_SERVER_NAME = "simple_music_player_single_instance_v1"

SUPPORTED_EXTS = {
    ".mp3", ".flac", ".wav", ".ogg", ".opus", ".m4a", ".aac", ".wma", ".webm"
}


def is_audio_file(path: str) -> bool:
    return os.path.isfile(path) and os.path.splitext(path)[1].lower() in SUPPORTED_EXTS


def normalize_paths(paths: List[str]) -> List[str]:
    out: List[str] = []
    for p in paths:
        if not p:
            continue
        p = os.path.abspath(str(p).strip().strip('"'))
        if is_audio_file(p):
            out.append(p)
    return out


def format_ms(ms: int) -> str:
    if ms < 0:
        ms = 0
    sec = ms // 1000
    m = sec // 60
    s = sec % 60
    return f"{m:02d}:{s:02d}"


def format_ms_detail(ms: int) -> str:
    if ms < 0:
        ms = 0
    total_ms = int(ms)
    sec = total_ms // 1000
    m = sec // 60
    s = sec % 60
    remain = total_ms % 1000
    return f"{m:02d}:{s:02d}.{remain:03d}"


def safe_title(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def app_base_dir() -> str:
    return os.path.dirname(os.path.abspath(sys.argv[0]))


def playlist_json_path() -> str:
    return os.path.join(app_base_dir(), "playlist.json")


def settings_json_path() -> str:
    return os.path.join(app_base_dir(), "settings.json")


@dataclass
class Track:
    path: str
    title: str
    artist: str
    album: str
    duration_ms: int
    checked: bool = False


def read_audio_metadata(path: str) -> Track:
    title = safe_title(path)
    artist = ""
    album = ""
    duration_ms = 0

    try:
        audio = MutagenFile(path, easy=True)
        if audio is not None:
            info = getattr(audio, "info", None)
            if info is not None:
                duration_ms = int(float(getattr(info, "length", 0.0) or 0.0) * 1000)

            def first_tag(name: str) -> str:
                try:
                    v = audio.get(name)
                    if isinstance(v, list) and v:
                        return str(v[0]).strip()
                    if isinstance(v, str):
                        return v.strip()
                except Exception:
                    pass
                return ""

            t = first_tag("title")
            a = first_tag("artist")
            al = first_tag("album")

            if t:
                title = t
            if a:
                artist = a
            if al:
                album = al
    except Exception:
        pass

    return Track(
        path=path,
        title=title,
        artist=artist,
        album=album,
        duration_ms=duration_ms,
        checked=False,
    )


def write_audio_metadata(path: str, title: str, artist: str, album: str) -> None:
    audio = MutagenFile(path, easy=True)
    if audio is None:
        raise RuntimeError("지원되지 않거나 읽을 수 없는 오디오 형식입니다.")

    if audio.tags is None and hasattr(audio, "add_tags"):
        try:
            audio.add_tags()
        except Exception:
            pass

    def set_or_remove(key: str, value: str) -> None:
        value = (value or "").strip()
        if value:
            audio[key] = [value]
        else:
            try:
                audio.pop(key, None)
            except Exception:
                pass

    set_or_remove("title", title)
    set_or_remove("artist", artist)
    set_or_remove("album", album)
    audio.save()


class PlayMode(Enum):
    REPEAT_ONE = auto()
    REPEAT_ALL = auto()
    REPEAT_CHECKED = auto()
    SHUFFLE_ALL = auto()
    SHUFFLE_CHECKED = auto()


class SingleInstanceBridge(QObject):
    message_received = Signal(dict)

    def __init__(self, server_name: str, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.server_name = server_name
        self.server = QLocalServer(self)

    def send_to_existing_instance(self, payload: dict) -> bool:
        socket = QLocalSocket(self)
        socket.connectToServer(self.server_name)
        if not socket.waitForConnected(250):
            return False

        try:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            socket.write(data)
            socket.flush()
            socket.waitForBytesWritten(500)
        finally:
            socket.disconnectFromServer()
        return True

    def start_listening(self) -> bool:
        try:
            QLocalServer.removeServer(self.server_name)
        except Exception:
            pass

        ok = self.server.listen(self.server_name)
        if ok:
            self.server.newConnection.connect(self._on_new_connection)
        return ok

    def _on_new_connection(self) -> None:
        socket = self.server.nextPendingConnection()
        if socket is None:
            return

        socket.waitForReadyRead(1000)
        raw = bytes(socket.readAll().data()).decode("utf-8", errors="ignore").strip()

        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {}

        self.message_received.emit(payload)
        socket.disconnectFromServer()
        socket.deleteLater()


class AudioEngine(QObject):
    track_finished = Signal()
    position_changed = Signal(int)
    duration_changed = Signal(int)
    error_text = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        self.audio_output = QAudioOutput()
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.8)

        self._pause_after_load = False
        self._seek_after_load = 0

        self.player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.player.positionChanged.connect(lambda p: self.position_changed.emit(int(p)))
        self.player.durationChanged.connect(lambda d: self.duration_changed.emit(int(d)))
        self.player.errorOccurred.connect(self._on_error_occurred)

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.track_finished.emit()
        elif status == QMediaPlayer.MediaStatus.BufferedMedia and self._seek_after_load > 0:
            pos = self._seek_after_load
            self._seek_after_load = 0
            self.player.setPosition(pos)
            if self._pause_after_load:
                self._pause_after_load = False
                self.player.pause()

    def _on_error_occurred(self, error: QMediaPlayer.Error, error_string: str) -> None:
        if error != QMediaPlayer.Error.NoError:
            self.error_text.emit(error_string or "오디오 재생 오류가 발생했습니다.")

    def available_output_devices(self) -> List[QAudioDevice]:
        return list(QMediaDevices.audioOutputs())

    def set_audio_device(self, device: QAudioDevice) -> None:
        self.audio_output.setDevice(device)

    def set_volume_0_100(self, value: int) -> None:
        value = max(0, min(100, int(value)))
        self.audio_output.setVolume(value / 100.0)

    def play_file(self, path: str) -> None:
        self._pause_after_load = False
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    def play_file_at(self, path: str, position_ms: int = 0) -> None:
        self._pause_after_load = False
        self._seek_after_load = max(0, position_ms)
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    def load_file_paused(self, path: str, position_ms: int = 0) -> None:
        self._pause_after_load = True
        self._seek_after_load = max(0, position_ms)
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    def play(self) -> None:
        self.player.play()

    def pause(self) -> None:
        self.player.pause()

    def stop(self) -> None:
        self.player.stop()

    def set_position(self, ms: int) -> None:
        self.player.setPosition(max(0, int(ms)))

    def position(self) -> int:
        return int(self.player.position())

    def duration(self) -> int:
        return int(self.player.duration())

    def has_valid_source(self) -> bool:
        return self.player.source().isValid()

    def playback_state(self) -> QMediaPlayer.PlaybackState:
        return self.player.playbackState()


class PlaybackController(QObject):
    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.tracks: List[Track] = []
        self.current_index: Optional[int] = None
        self.mode: PlayMode = PlayMode.REPEAT_CHECKED
        self.shuffle_bag: List[int] = []
        self.history: List[int] = []

    def set_tracks(self, tracks: List[Track]) -> None:
        self.tracks = tracks
        if self.current_index is not None and not (0 <= self.current_index < len(self.tracks)):
            self.current_index = None
        self.invalidate_dynamic_state()

    def set_mode(self, mode: PlayMode) -> None:
        self.mode = mode
        self.invalidate_dynamic_state()

    def set_current_index(self, index: Optional[int], push_history: bool = True) -> None:
        if index is None:
            self.current_index = None
            return

        if not (0 <= index < len(self.tracks)):
            return

        if push_history and self.current_index is not None and self.current_index != index:
            self.history.append(self.current_index)

        self.current_index = index

    def invalidate_dynamic_state(self) -> None:
        self.shuffle_bag.clear()

    def all_indices(self) -> List[int]:
        return list(range(len(self.tracks)))

    def checked_indices(self) -> List[int]:
        return [i for i, t in enumerate(self.tracks) if t.checked]

    def _next_in_pool(self, pool: List[int], current: Optional[int]) -> Optional[int]:
        if not pool:
            return None
        if current is None or current not in pool:
            return pool[0]
        pos = pool.index(current)
        return pool[(pos + 1) % len(pool)]

    def _prev_in_pool(self, pool: List[int], current: Optional[int]) -> Optional[int]:
        if not pool:
            return None
        if current is None or current not in pool:
            return pool[-1]
        pos = pool.index(current)
        return pool[(pos - 1) % len(pool)]

    def _rebuild_shuffle_bag(self, pool: List[int], avoid_first: Optional[int] = None) -> None:
        bag = pool[:]
        random.shuffle(bag)

        if avoid_first is not None and len(bag) > 1 and bag[0] == avoid_first:
            for i in range(1, len(bag)):
                if bag[i] != avoid_first:
                    bag[0], bag[i] = bag[i], bag[0]
                    break

        self.shuffle_bag = bag

    def _next_random_from_pool(self, pool: List[int]) -> Optional[int]:
        if not pool:
            return None
        if len(pool) == 1:
            return pool[0]

        if not self.shuffle_bag or set(self.shuffle_bag) != set(pool):
            self._rebuild_shuffle_bag(pool, avoid_first=self.current_index)

        while self.shuffle_bag:
            idx = self.shuffle_bag.pop(0)
            if idx != self.current_index:
                return idx

        self._rebuild_shuffle_bag(pool, avoid_first=self.current_index)
        if self.shuffle_bag:
            return self.shuffle_bag.pop(0)
        return None

    def choose_next_auto(self) -> Optional[int]:
        if not self.tracks:
            return None

        if self.mode == PlayMode.REPEAT_ONE:
            return self.current_index

        if self.mode == PlayMode.REPEAT_ALL:
            return self._next_in_pool(self.all_indices(), self.current_index)

        if self.mode == PlayMode.REPEAT_CHECKED:
            return self._next_in_pool(self.checked_indices(), self.current_index)

        if self.mode == PlayMode.SHUFFLE_ALL:
            return self._next_random_from_pool(self.all_indices())

        if self.mode == PlayMode.SHUFFLE_CHECKED:
            return self._next_random_from_pool(self.checked_indices())

        return None

    def choose_next_manual(self) -> Optional[int]:
        if not self.tracks:
            return None

        if self.mode == PlayMode.REPEAT_ONE:
            return self._next_in_pool(self.all_indices(), self.current_index)

        return self.choose_next_auto()

    def choose_prev_manual(self) -> Optional[int]:
        if not self.tracks:
            return None

        if self.mode in (PlayMode.SHUFFLE_ALL, PlayMode.SHUFFLE_CHECKED):
            while self.history:
                idx = self.history.pop()
                if 0 <= idx < len(self.tracks):
                    if self.mode == PlayMode.SHUFFLE_CHECKED and not self.tracks[idx].checked:
                        continue
                    return idx

            pool = self.checked_indices() if self.mode == PlayMode.SHUFFLE_CHECKED else self.all_indices()
            return self._prev_in_pool(pool, self.current_index)

        if self.mode == PlayMode.REPEAT_CHECKED:
            return self._prev_in_pool(self.checked_indices(), self.current_index)

        return self._prev_in_pool(self.all_indices(), self.current_index)


class TagEditDialog(QDialog):
    def __init__(self, track: Track, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("태그 편집")
        self.resize(520, 180)

        form = QFormLayout(self)

        self.ed_title = QLineEdit(track.title)
        self.ed_artist = QLineEdit(track.artist)
        self.ed_album = QLineEdit(track.album)
        self.ed_path = QLineEdit(track.path)
        self.ed_path.setReadOnly(True)

        form.addRow("제목", self.ed_title)
        form.addRow("아티스트", self.ed_artist)
        form.addRow("앨범", self.ed_album)
        form.addRow("경로", self.ed_path)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        form.addRow(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    def values(self) -> tuple[str, str, str]:
        return (
            self.ed_title.text().strip(),
            self.ed_artist.text().strip(),
            self.ed_album.text().strip(),
        )


class CheckBoxDelegate(QStyledItemDelegate):
    def paint(self, painter: Any, option: Any, index: Any) -> None:
        if painter is None:
            return
        style = option.widget.style() if option.widget else QApplication.style()
        if style is None:
            return
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget)

        cb_opt = QStyleOptionButton()
        cb_opt.state = QStyle.StateFlag.State_Enabled
        check_val = index.data(Qt.ItemDataRole.CheckStateRole)
        if check_val == Qt.CheckState.Checked or check_val == 2:
            cb_opt.state |= QStyle.StateFlag.State_On
        else:
            cb_opt.state |= QStyle.StateFlag.State_Off

        from PySide6.QtCore import QSize, QRect
        cb_size: QSize = style.subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator, cb_opt, option.widget,
        ).size()
        cb_rect = QRect(
            option.rect.left() + (option.rect.width() - cb_size.width()) // 2,
            option.rect.top() + (option.rect.height() - cb_size.height()) // 2,
            cb_size.width(),
            cb_size.height(),
        )
        cb_opt.rect = cb_rect
        style.drawControl(QStyle.ControlElement.CE_CheckBox, cb_opt, painter, option.widget)

    def editorEvent(self, event: Any, model: Any, option: Any, index: Any) -> bool:
        from PySide6.QtCore import QEvent
        if event.type() in (QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            check_val = index.data(Qt.ItemDataRole.CheckStateRole)
            if check_val == Qt.CheckState.Checked or check_val == 2:
                new_state = Qt.CheckState.Unchecked
            else:
                new_state = Qt.CheckState.Checked
            model.setData(index, new_state, Qt.ItemDataRole.CheckStateRole)
            return True
        return False


class CheckBoxHeader(QHeaderView):
    check_state_changed = Signal(Qt.CheckState)

    def __init__(self, parent: QTableWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._check_state = Qt.CheckState.Unchecked

    def set_check_state(self, state: Qt.CheckState) -> None:
        if self._check_state != state:
            self._check_state = state
            self.viewport().update()

    def paintSection(self, painter: Any, rect: Any, logicalIndex: int) -> None:
        if painter is None:
            return
        painter.save()
        super().paintSection(painter, rect, logicalIndex)
        painter.restore()

        if logicalIndex != 0:
            return

        style = self.style()
        if style is None:
            return

        cb_opt = QStyleOptionButton()
        cb_opt.state = QStyle.StateFlag.State_Enabled
        if self._check_state == Qt.CheckState.Checked:
            cb_opt.state |= QStyle.StateFlag.State_On
        elif self._check_state == Qt.CheckState.PartiallyChecked:
            cb_opt.state |= QStyle.StateFlag.State_NoChange
        else:
            cb_opt.state |= QStyle.StateFlag.State_Off

        from PySide6.QtCore import QSize, QRect as QR
        cb_size: QSize = style.subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator, cb_opt, self,
        ).size()
        cb_rect = QR(
            rect.left() + (rect.width() - cb_size.width()) // 2,
            rect.top() + (rect.height() - cb_size.height()) // 2,
            cb_size.width(),
            cb_size.height(),
        )
        cb_opt.rect = cb_rect
        style.drawControl(QStyle.ControlElement.CE_CheckBox, cb_opt, painter, self)

    def mousePressEvent(self, event: Any) -> None:
        if event is not None and self.logicalIndexAt(event.pos()) == 0:
            if self._check_state == Qt.CheckState.Checked:
                new_state = Qt.CheckState.Unchecked
            else:
                new_state = Qt.CheckState.Checked
            self._check_state = new_state
            self.viewport().update()
            self.check_state_changed.emit(new_state)
        else:
            super().mousePressEvent(event)


class PlaylistTable(QTableWidget):
    files_dropped = Signal(list)
    rows_moved = Signal(list, int)

    def __init__(self, rows: int, columns: int, parent: QWidget | None = None) -> None:
        super().__init__(rows, columns, parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)
        self._drag_rows: List[int] = []

    def startDrag(self, supportedActions: Qt.DropAction) -> None:
        self._drag_rows = sorted({idx.row() for idx in self.selectedIndexes()})
        super().startDrag(supportedActions)

    def dragEnterEvent(self, e: QDragEnterEvent | None) -> None:
        if e is None:
            return
        md = e.mimeData()
        if md and (md.hasUrls() or e.source() is self):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e: QDragMoveEvent | None) -> None:
        if e is None:
            return
        md = e.mimeData()
        if md and (md.hasUrls() or e.source() is self):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, event: QDropEvent | None) -> None:
        if event is None:
            return
        md = event.mimeData()
        if md and md.hasUrls():
            paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
            if paths:
                self.files_dropped.emit(paths)
            event.acceptProposedAction()
            return
        if event.source() is self and self._drag_rows:
            pos = event.position()
            target = self.indexAt(QPoint(int(pos.x()), int(pos.y()))).row()
            if target < 0:
                target = self.rowCount()
            self.rows_moved.emit(list(self._drag_rows), target)
            event.acceptProposedAction()
            self._drag_rows = []
            return
        event.ignore()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self._default_title = "Simple Music Player"
        self.setWindowTitle(self._default_title)
        self.resize(1180, 720)
        self.setMinimumWidth(400)

        self.tracks: List[Track] = []
        self.table_updating = False
        self.user_dragging_progress = False
        self.current_duration_ms = 0
        self.pending_ab_reset = False
        self.last_open_dir: str = ""

        self.engine = AudioEngine(self)
        self.controller = PlaybackController(self)

        self.engine.track_finished.connect(self._on_track_finished)
        self.engine.position_changed.connect(self._on_position_changed)
        self.engine.duration_changed.connect(self._on_duration_changed)
        self.engine.error_text.connect(self._on_error_text)

        self._build_ui()
        self._apply_light_ui()
        self._init_tray()
        self._load_devices()
        self._install_shortcuts()
        self._restore_settings()
        self._load_playlist_from_disk()

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)

        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(6, 6, 6, 6)
        root_layout.setSpacing(4)

        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs)

        # ── 재생 탭 ──
        player_tab = QWidget()
        main = QVBoxLayout(player_tab)
        main.setContentsMargins(4, 4, 4, 4)
        main.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(4)

        self.btn_prev = QToolButton()
        self.btn_prev.setIcon(self._create_prev_icon())
        self.btn_prev.setIconSize(QSize(14, 14))

        self.btn_play = QToolButton()
        self.btn_play.setIcon(self._create_play_icon())
        self.btn_play.setIconSize(QSize(14, 14))

        self.btn_pause = QToolButton()
        self.btn_pause.setIcon(self._create_pause_icon())
        self.btn_pause.setIconSize(QSize(14, 14))

        self.btn_stop = QToolButton()
        self.btn_stop.setIcon(self._create_stop_icon())
        self.btn_stop.setIconSize(QSize(14, 14))

        self.btn_next = QToolButton()
        self.btn_next.setIcon(self._create_next_icon())
        self.btn_next.setIconSize(QSize(14, 14))

        self.cmb_mode = QComboBox()
        self.cmb_mode.setFixedHeight(24)
        self.cmb_mode.addItem("한곡 반복", PlayMode.REPEAT_ONE)
        self.cmb_mode.addItem("전체 반복", PlayMode.REPEAT_ALL)
        self.cmb_mode.addItem("전체 랜덤", PlayMode.SHUFFLE_ALL)
        self.cmb_mode.addItem("체크 반복", PlayMode.REPEAT_CHECKED)
        self.cmb_mode.addItem("체크 랜덤", PlayMode.SHUFFLE_CHECKED)

        self.cmb_device = QComboBox()
        self.cmb_device.setFixedHeight(24)

        self.sld_volume = QSlider(Qt.Orientation.Horizontal)
        self.sld_volume.setRange(0, 100)
        self.sld_volume.setValue(80)
        self.sld_volume.setFixedWidth(140)
        self.sld_volume.setFixedHeight(20)

        self.cmb_mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.cmb_device.setMinimumWidth(60)
        self.sld_volume.setFixedWidth(80)

        top.addWidget(self.btn_play)
        top.addWidget(self.btn_pause)
        top.addWidget(self.btn_stop)
        top.addWidget(self.btn_prev)
        top.addWidget(self.btn_next)
        top.addSpacing(4)
        top.addWidget(QLabel("Order:"))
        top.addWidget(self.cmb_mode)

        top.addWidget(self.sld_volume)

        main.addLayout(top)

        progress = QHBoxLayout()
        progress.setSpacing(4)

        self.sld_progress = QSlider(Qt.Orientation.Horizontal)
        self.sld_progress.setRange(0, 0)
        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setFixedWidth(95)

        progress.addWidget(self.sld_progress, 1)
        progress.addWidget(self.lbl_time)

        main.addLayout(progress)

        self.lbl_now = QLabel("대기")
        main.addWidget(self.lbl_now)

        ab1 = QHBoxLayout()
        ab1.setSpacing(4)

        self.chk_ab = QCheckBox("A-B 반복")
        self.btn_set_a = QPushButton("현재위치→A")
        self.btn_set_a.setFixedHeight(24)

        self.sld_a = QSlider(Qt.Orientation.Horizontal)
        self.sld_a.setRange(0, 0)

        self.ed_a = QLineEdit("00:00.000")
        self.ed_a.setReadOnly(True)
        self.ed_a.setFixedWidth(95)
        self.ed_a.setFixedHeight(24)

        ab1.addWidget(self.chk_ab)
        ab1.addWidget(QLabel("A"))
        ab1.addWidget(self.sld_a, 1)
        ab1.addWidget(self.ed_a)
        ab1.addWidget(self.btn_set_a)

        main.addLayout(ab1)

        ab2 = QHBoxLayout()
        ab2.setSpacing(4)

        self.btn_set_b = QPushButton("현재위치→B")
        self.btn_set_b.setFixedHeight(24)

        self.sld_b = QSlider(Qt.Orientation.Horizontal)
        self.sld_b.setRange(0, 0)

        self.ed_b = QLineEdit("00:00.000")
        self.ed_b.setReadOnly(True)
        self.ed_b.setFixedWidth(95)
        self.ed_b.setFixedHeight(24)

        ab2.addWidget(QLabel("B"))
        ab2.addWidget(self.sld_b, 1)
        ab2.addWidget(self.ed_b)
        ab2.addWidget(self.btn_set_b)

        main.addLayout(ab2)

        self.table = PlaylistTable(0, 4)
        self.check_header = CheckBoxHeader(self.table)
        self.table.setHorizontalHeader(self.check_header)
        self.table.setHorizontalHeaderLabels(["", "제목", "아티스트", "길이"])
        self.table.setItemDelegateForColumn(0, CheckBoxDelegate(self.table))
        self.check_header.check_state_changed.connect(self._on_header_check_changed)
        v_header = self.table.verticalHeader()
        if v_header:
            v_header.setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        h_header = self.table.horizontalHeader()
        if h_header:
            h_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            h_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            h_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(2, self.fontMetrics().horizontalAdvance("Puff Daddy" + "WW"))
            h_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        main.addWidget(self.table, 1)

        self.edt_search = QLineEdit()
        self.edt_search.setPlaceholderText("검색...")
        self.edt_search.setClearButtonEnabled(True)
        self.edt_search.textChanged.connect(self._on_search_changed)
        main.addWidget(self.edt_search)

        self.lbl_status = QLabel("준비됨")
        main.addWidget(self.lbl_status)

        self.tabs.addTab(player_tab, "재생")

        # ── 설정 탭 ──
        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)
        settings_layout.setContentsMargins(12, 12, 12, 12)
        settings_layout.setSpacing(8)

        chk_row = QHBoxLayout()
        chk_row.setSpacing(12)
        self.chk_always_on_top = QCheckBox("최상위")
        self.chk_always_on_top.toggled.connect(self._on_always_on_top_changed)
        chk_row.addWidget(self.chk_always_on_top)
        self.chk_auto_play = QCheckBox("실행 시 자동 재생")
        self.chk_auto_play.toggled.connect(lambda: self._save_settings())
        chk_row.addWidget(self.chk_auto_play)
        self.chk_close_to_tray = QCheckBox("종료시 트레이로")
        self.chk_close_to_tray.toggled.connect(self._on_close_to_tray_changed)
        chk_row.addWidget(self.chk_close_to_tray)
        chk_row.addStretch()
        settings_layout.addLayout(chk_row)

        restore_row = QHBoxLayout()
        self.btn_restore_size = QPushButton("이전 크기로 복원")
        self.btn_restore_size.setFixedWidth(120)
        self.btn_restore_size.clicked.connect(self._restore_previous_size)
        restore_row.addWidget(self.btn_restore_size)
        restore_row.addStretch()
        settings_layout.addLayout(restore_row)

        device_row = QHBoxLayout()
        device_row.setSpacing(6)
        device_row.addWidget(QLabel("재생 장치:"))
        device_row.addWidget(self.cmb_device, 1)
        settings_layout.addLayout(device_row)

        font_row = QHBoxLayout()
        font_row.setSpacing(6)
        font_row.addWidget(QLabel("글꼴:"))
        self.cmb_font = QFontComboBox()
        font_row.addWidget(self.cmb_font, 1)
        font_row.addWidget(QLabel("크기:"))
        self.spn_font_size = QSpinBox()
        self.spn_font_size.setRange(7, 24)
        self.spn_font_size.setValue(9)
        font_row.addWidget(self.spn_font_size)
        settings_layout.addLayout(font_row)

        self.cmb_font.currentFontChanged.connect(self._apply_font)
        self.spn_font_size.valueChanged.connect(self._apply_font)

        settings_layout.addStretch()

        save_row = QHBoxLayout()
        self.btn_save_settings = QPushButton("현재 설정 저장")
        self.btn_save_settings.setFixedWidth(120)
        self.btn_save_settings.clicked.connect(self._on_save_settings_clicked)
        save_row.addStretch()
        save_row.addWidget(self.btn_save_settings)
        settings_layout.addLayout(save_row)

        self.tabs.addTab(settings_tab, "설정")

        # ── 시그널 연결 ──
        self.btn_prev.clicked.connect(self.on_prev_clicked)
        self.btn_play.clicked.connect(self.on_play_clicked)
        self.btn_pause.clicked.connect(self.on_pause_clicked)
        self.btn_stop.clicked.connect(self.on_stop_clicked)
        self.btn_next.clicked.connect(self.on_next_clicked)

        self.cmb_mode.currentIndexChanged.connect(self.on_mode_changed)
        self.cmb_device.currentIndexChanged.connect(self.on_device_changed)
        self.sld_volume.valueChanged.connect(self.on_volume_changed)

        self.sld_progress.sliderPressed.connect(self.on_progress_pressed)
        self.sld_progress.sliderReleased.connect(self.on_progress_released)

        self.sld_a.valueChanged.connect(self.on_a_slider_changed)
        self.sld_b.valueChanged.connect(self.on_b_slider_changed)
        self.btn_set_a.clicked.connect(self.on_set_a_from_current)
        self.btn_set_b.clicked.connect(self.on_set_b_from_current)

        self.table.itemChanged.connect(self.on_table_item_changed)
        self.table.cellDoubleClicked.connect(self.on_table_double_clicked)
        self.table.customContextMenuRequested.connect(self.on_table_context_menu)
        self.table.files_dropped.connect(self._on_files_dropped)
        self.table.rows_moved.connect(self._on_rows_moved)

    def _apply_light_ui(self) -> None:
        for btn in (self.btn_prev, self.btn_play, self.btn_pause, self.btn_stop, self.btn_next):
            btn.setAutoRaise(True)
            btn.setFixedSize(24, 24)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        self.setStyleSheet("""
            QToolButton {
                padding: 0px;
                margin: 0px;
            }
            QTableWidget {
                background: white;
                alternate-background-color: white;
            }
            QTableWidget::item:focus {
                outline: none;
                border: none;
            }
            QTableWidget::item:selected {
                background: #0078d7;
                color: white;
            }
            QLineEdit[readOnly="true"] {
                background: white;
            }
        """)

    def _create_play_icon(self) -> QIcon:
        px = QPixmap(32, 32)
        px.fill(QColor(0, 0, 0, 0))
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        from PySide6.QtGui import QPolygon
        from PySide6.QtCore import QPoint as QP
        p.drawPolygon(QPolygon([QP(6, 3), QP(28, 16), QP(6, 29)]))
        p.end()
        return QIcon(px)

    def _create_pause_icon(self) -> QIcon:
        px = QPixmap(32, 32)
        px.fill(QColor(0, 0, 0, 0))
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRect(6, 4, 7, 24))
        p.drawRect(QRect(19, 4, 7, 24))
        p.end()
        return QIcon(px)

    def _create_prev_icon(self) -> QIcon:
        px = QPixmap(32, 32)
        px.fill(QColor(0, 0, 0, 0))
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRect(3, 4, 5, 24))
        from PySide6.QtGui import QPolygon
        from PySide6.QtCore import QPoint as QP
        p.drawPolygon(QPolygon([QP(28, 3), QP(10, 16), QP(28, 29)]))
        p.end()
        return QIcon(px)

    def _create_next_icon(self) -> QIcon:
        px = QPixmap(32, 32)
        px.fill(QColor(0, 0, 0, 0))
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        from PySide6.QtGui import QPolygon
        from PySide6.QtCore import QPoint as QP
        p.drawPolygon(QPolygon([QP(4, 3), QP(22, 16), QP(4, 29)]))
        p.drawRect(QRect(24, 4, 5, 24))
        p.end()
        return QIcon(px)

    def _create_stop_icon(self) -> QIcon:
        px = QPixmap(32, 32)
        px.fill(QColor(0, 0, 0, 0))
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRect(4, 4, 24, 24))
        p.end()
        return QIcon(px)

    def _set_tray_icon(self, pixmap: QStyle.StandardPixmap) -> None:
        if self.tray is None:
            return
        style = self.style()
        if style is not None:
            self.tray.setIcon(style.standardIcon(pixmap))

    def _on_close_to_tray_changed(self, checked: bool) -> None:
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setQuitOnLastWindowClosed(not checked)
        if not getattr(self, "_restoring", False):
            self._save_settings()

    def _on_always_on_top_changed(self, checked: bool) -> None:
        if getattr(self, "_restoring", False):
            return
        if checked:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
        self.show()
        self._save_settings()

    def _apply_font(self) -> None:
        font = QFont(self.cmb_font.currentFont().family(), self.spn_font_size.value())
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setFont(font)

    def _init_tray(self) -> None:
        self.tray: Optional[QSystemTrayIcon] = None

        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._set_status("시스템 트레이를 사용할 수 없습니다.")
            return

        style = self.style()
        if style is not None:
            icon = style.standardIcon(QStyle.StandardPixmap.SP_MediaStop)
            self.tray = QSystemTrayIcon(icon, self)
        else:
            self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip("Simple Music Player")

        menu = QMenu(self)
        act_play = QAction("재생", self)
        act_pause = QAction("일시정지", self)
        act_stop = QAction("정지", self)
        act_show = QAction("표시", self)
        act_quit = QAction("종료", self)

        act_play.triggered.connect(self.on_play_clicked)
        act_pause.triggered.connect(self.on_pause_clicked)
        act_stop.triggered.connect(self.on_stop_clicked)
        act_show.triggered.connect(self.show_from_tray)
        act_quit.triggered.connect(self.quit_app)

        menu.addAction(act_play)
        menu.addAction(act_pause)
        menu.addAction(act_stop)
        menu.addSeparator()
        menu.addAction(act_show)
        menu.addAction(act_quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

    def on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if not hasattr(self, "_tray_click_timer"):
                self._tray_click_timer = QTimer(self)
                self._tray_click_timer.setSingleShot(True)
                self._tray_click_timer.timeout.connect(self.toggle_play_pause)
            self._tray_click_timer.start(300)
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if hasattr(self, "_tray_click_timer"):
                self._tray_click_timer.stop()
            self.show_from_tray()

    def show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        if self.chk_close_to_tray.isChecked() and self.tray is not None:
            if a0:
                a0.ignore()
            self.hide()
            return
        self._save_settings()
        self._save_playlist_to_disk()
        self.engine.stop()
        if self.tray is not None:
            self.tray.hide()
        if a0:
            a0.accept()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def quit_app(self) -> None:
        self._save_settings()
        self._save_playlist_to_disk()
        self.engine.stop()
        if self.tray is not None:
            self.tray.hide()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _install_shortcuts(self) -> None:
        self.sc_toggle = QShortcut(QKeySequence("Space"), self)
        self.sc_toggle.setContext(Qt.ShortcutContext.WindowShortcut)
        self.sc_toggle.activated.connect(self.toggle_play_pause)

        self.sc_left = QShortcut(QKeySequence("Left"), self)
        self.sc_left.setContext(Qt.ShortcutContext.WindowShortcut)
        self.sc_left.activated.connect(lambda: self.seek_relative(-5000))

        self.sc_right = QShortcut(QKeySequence("Right"), self)
        self.sc_right.setContext(Qt.ShortcutContext.WindowShortcut)
        self.sc_right.activated.connect(lambda: self.seek_relative(5000))

        self.sc_delete = QShortcut(QKeySequence("Delete"), self)
        self.sc_delete.setContext(Qt.ShortcutContext.WindowShortcut)
        self.sc_delete.activated.connect(self.on_delete_selected)

        self.sc_home = QShortcut(QKeySequence("Home"), self)
        self.sc_home.setContext(Qt.ShortcutContext.WindowShortcut)
        self.sc_home.activated.connect(lambda: self._scroll_to_row(0))

        self.sc_end = QShortcut(QKeySequence("End"), self)
        self.sc_end.setContext(Qt.ShortcutContext.WindowShortcut)
        self.sc_end.activated.connect(lambda: self._scroll_to_row(len(self.tracks) - 1))

    def _scroll_to_row(self, row: int) -> None:
        if 0 <= row < self.table.rowCount():
            self.table.selectRow(row)
            item = self.table.item(row, 0)
            if item is not None:
                self.table.scrollToItem(item)

    def _set_status(self, text: str) -> None:
        self.lbl_status.setText(text)
        if self.tray is not None:
            if text == "재생":
                self._set_tray_icon(QStyle.StandardPixmap.SP_MediaPlay)
            elif text == "일시정지":
                self._set_tray_icon(QStyle.StandardPixmap.SP_MediaPause)
            elif text == "정지":
                self._set_tray_icon(QStyle.StandardPixmap.SP_MediaStop)

    def _save_settings(self) -> None:
        if getattr(self, "_restoring", False):
            return
        geo = self.geometry()
        data = {
            "x": geo.x(),
            "y": geo.y(),
            "width": geo.width(),
            "height": geo.height(),
            "volume": self.sld_volume.value(),
            "mode_index": self.cmb_mode.currentIndex(),
            "last_open_dir": self.last_open_dir,
            "device_name": self.cmb_device.currentText(),
            "current_track_index": self.controller.current_index if self.controller.current_index is not None else -1,
            "playback_position": self.engine.position(),
            "ab_enabled": self.chk_ab.isChecked(),
            "ab_a_value": self.sld_a.value(),
            "ab_b_value": self.sld_b.value(),
            "auto_play": self.chk_auto_play.isChecked(),
            "close_to_tray": self.chk_close_to_tray.isChecked(),
            "always_on_top": self.chk_always_on_top.isChecked(),
            "font_family": self.cmb_font.currentFont().family(),
            "font_size": self.spn_font_size.value(),
        }
        try:
            with open(settings_json_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _on_save_settings_clicked(self) -> None:
        self._save_settings()
        self.lbl_status.setText("설정이 저장되었습니다.")

    def _restore_previous_size(self) -> None:
        if hasattr(self, "_initial_geometry"):
            geo = self._initial_geometry
            self.setGeometry(geo)

    def _restore_settings(self) -> None:
        self._restoring = True

        s: dict = {}
        try:
            with open(settings_json_path(), "r", encoding="utf-8") as f:
                s = json.load(f)
        except Exception:
            pass

        if "x" in s and "y" in s and "width" in s and "height" in s:
            from PySide6.QtGui import QGuiApplication
            x, y, w, h = int(s["x"]), int(s["y"]), int(s["width"]), int(s["height"])
            visible = False
            for screen in QGuiApplication.screens():
                if screen.availableGeometry().intersects(
                    self.geometry().__class__(x, y, w, h)
                ):
                    visible = True
                    break
            if visible:
                self.setGeometry(x, y, w, h)
            else:
                self.resize(w, h)
            self._initial_geometry = self.geometry()

        volume = int(s.get("volume", 80))
        mode_index = int(s.get("mode_index", 2))

        self.sld_volume.setValue(volume)
        if 0 <= mode_index < self.cmb_mode.count():
            self.cmb_mode.setCurrentIndex(mode_index)
        mode = self.cmb_mode.itemData(self.cmb_mode.currentIndex())
        if isinstance(mode, PlayMode):
            self.controller.set_mode(mode)

        self.last_open_dir = str(s.get("last_open_dir", ""))

        saved_device = str(s.get("device_name", ""))
        if saved_device:
            for i in range(self.cmb_device.count()):
                if self.cmb_device.itemText(i) == saved_device:
                    self.cmb_device.setCurrentIndex(i)
                    break

        self._saved_track_index = int(s.get("current_track_index", -1))
        self._saved_position = int(s.get("playback_position", 0))
        self._saved_ab_enabled = bool(s.get("ab_enabled", False))
        self._saved_ab_a = int(s.get("ab_a_value", 0))
        self._saved_ab_b = int(s.get("ab_b_value", 0))

        self.chk_auto_play.setChecked(bool(s.get("auto_play", True)))
        self._saved_auto_play = self.chk_auto_play.isChecked()

        self.chk_close_to_tray.setChecked(bool(s.get("close_to_tray", False)))

        on_top = bool(s.get("always_on_top", False))
        self.chk_always_on_top.setChecked(on_top)
        if on_top:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        font_family = str(s.get("font_family", ""))
        font_size = int(s.get("font_size", 9))
        self.spn_font_size.setValue(font_size)
        if font_family:
            self.cmb_font.setCurrentFont(QFont(font_family))
        self._apply_font()

        self._restoring = False

    def _save_playlist_to_disk(self) -> None:
        try:
            data = [asdict(t) for t in self.tracks]
            with open(playlist_json_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._set_status(f"재생목록 저장 실패: {e}")

    def _load_playlist_from_disk(self) -> None:
        path = playlist_json_path()
        if not os.path.isfile(path):
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)

            loaded: List[Track] = []
            for item in raw:
                p = str(item.get("path", "")).strip()
                if not p or not os.path.isfile(p):
                    continue

                loaded.append(
                    Track(
                        path=p,
                        title=str(item.get("title", safe_title(p))),
                        artist=str(item.get("artist", "")),
                        album=str(item.get("album", "")),
                        duration_ms=int(item.get("duration_ms", 0)),
                        checked=bool(item.get("checked", False)),
                    )
                )

            self.tracks = loaded
            self._rebuild_table()
            self._sync_tracks()

            idx = getattr(self, "_saved_track_index", -1)
            pos = getattr(self, "_saved_position", 0)
            ab_on = getattr(self, "_saved_ab_enabled", False)
            ab_a = getattr(self, "_saved_ab_a", 0)
            ab_b = getattr(self, "_saved_ab_b", 0)

            if 0 <= idx < len(self.tracks):
                track = self.tracks[idx]
                if os.path.isfile(track.path):
                    self.controller.set_current_index(idx, push_history=False)
                    self.pending_ab_reset = False
                    if getattr(self, "_saved_auto_play", True):
                        self.engine.play_file_at(track.path, pos)
                    else:
                        self.engine.load_file_paused(track.path, pos)
                    self.table.selectRow(idx)
                    self.lbl_now.setText(f"재생 중: {track.title}")
                    self.setWindowTitle(f"{track.artist} - {track.title}" if track.artist else track.title)
                    if self.tray is not None:
                        self.tray.setToolTip(f"{track.artist} - {track.title}" if track.artist else track.title)
                        self._set_tray_icon(QStyle.StandardPixmap.SP_MediaPlay)

                    if ab_a > 0 or ab_b > 0:
                        self.sld_a.setValue(ab_a)
                        self.sld_b.setValue(ab_b)
                    if ab_on:
                        self.chk_ab.setChecked(True)

            self._set_status(f"재생목록 복원: {len(self.tracks)}개")
        except Exception as e:
            self._set_status(f"재생목록 복원 실패: {e}")

    def _load_devices(self) -> None:
        self.cmb_device.clear()
        devices = self.engine.available_output_devices()
        for device in devices:
            self.cmb_device.addItem(device.description(), device)

        if self.cmb_device.count() > 0:
            self.cmb_device.setCurrentIndex(0)
            data = self.cmb_device.currentData()
            if isinstance(data, QAudioDevice):
                self.engine.set_audio_device(data)

    def on_device_changed(self, index: int) -> None:
        device = self.cmb_device.itemData(index)
        if isinstance(device, QAudioDevice):
            self.engine.set_audio_device(device)
            self._set_status(f"출력장치: {device.description()}")

    def on_volume_changed(self, value: int) -> None:
        self.engine.set_volume_0_100(value)

    def _sync_tracks(self) -> None:
        self.controller.set_tracks(self.tracks)

    def _rebuild_table(self) -> None:
        self.table_updating = True
        self.table.setRowCount(0)

        for row, track in enumerate(self.tracks):
            self.table.insertRow(row)

            item_check = QTableWidgetItem()
            item_check.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            item_check.setCheckState(
                Qt.CheckState.Checked if track.checked else Qt.CheckState.Unchecked
            )

            self.table.setItem(row, 0, item_check)
            tip = f"{track.artist} - {track.title}" if track.artist else track.title
            item_title = QTableWidgetItem(track.title)
            item_title.setToolTip(tip)
            item_artist = QTableWidgetItem(track.artist)
            item_artist.setToolTip(tip)
            item_dur = QTableWidgetItem(format_ms(track.duration_ms))
            item_dur.setToolTip(tip)
            self.table.setItem(row, 1, item_title)
            self.table.setItem(row, 2, item_artist)
            self.table.setItem(row, 3, item_dur)

        self.table_updating = False
        self._update_header_check_state()

    def _append_track(self, track: Track) -> int:
        self.tracks.append(track)
        return len(self.tracks) - 1

    def _append_paths(self, paths: List[str]) -> List[int]:
        existing = {os.path.normpath(t.path).lower(): i for i, t in enumerate(self.tracks)}
        rows: List[int] = []
        added = False
        for p in paths:
            key = os.path.normpath(p).lower()
            if key in existing:
                rows.append(existing[key])
            else:
                tr = read_audio_metadata(p)
                row = self._append_track(tr)
                existing[key] = row
                rows.append(row)
                added = True

        if added:
            self._rebuild_table()
            self._sync_tracks()
            self._save_playlist_to_disk()

        return rows

    def _refresh_track_metadata(self, row: int) -> None:
        if not (0 <= row < len(self.tracks)):
            return
        checked = self.tracks[row].checked
        new_tr = read_audio_metadata(self.tracks[row].path)
        new_tr.checked = checked
        self.tracks[row] = new_tr
        self._rebuild_table()
        self._sync_tracks()
        self._save_playlist_to_disk()

    def _reindex_after_remove(self, removed_rows: List[int]) -> None:
        if self.controller.current_index is None:
            self._sync_tracks()
            return

        current = self.controller.current_index
        removed_set = set(removed_rows)

        if current in removed_set:
            self.controller.set_current_index(None, push_history=False)
            self.engine.stop()
            self.setWindowTitle(self._default_title)
            if self.tray is not None:
                self.tray.setToolTip(self._default_title)
                self._set_tray_icon(QStyle.StandardPixmap.SP_MediaStop)
            self.lbl_now.setText("현재 재생곡이 삭제되어 정지됨")
        else:
            shift = sum(1 for r in removed_rows if r < current)
            self.controller.set_current_index(current - shift, push_history=False)

        self._sync_tracks()

    def on_add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "음악 파일 선택",
            self.last_open_dir,
            "Audio Files (*.mp3 *.flac *.wav *.ogg *.opus *.m4a *.aac *.wma *.webm);;All Files (*)"
        )
        if not paths:
            return

        self.last_open_dir = os.path.dirname(paths[0])
        rows = self._append_paths(normalize_paths(paths))
        self._set_status(f"{len(rows)}개 파일 추가")

    def on_import_foobar2000(self) -> None:
        fpl_path, _ = QFileDialog.getOpenFileName(
            self,
            "foobar2000 재생목록 선택",
            r"D:\Music\foobar2000\playlists-v1.4",
            "foobar2000 Playlist (*.fpl);;All Files (*)",
        )
        if not fpl_path:
            return

        try:
            import re
            with open(fpl_path, "rb") as f:
                data = f.read()
            raw_paths = [m.decode("utf-8", errors="replace")
                         for m in re.findall(rb"file://([^\x00]+)", data)]
            paths = normalize_paths(raw_paths)
            if not paths:
                self._set_status("가져올 수 있는 오디오 파일이 없습니다.")
                return
            rows = self._append_paths(paths)
            self._set_status(f"foobar2000에서 {len(rows)}개 파일 가져옴")
        except Exception as e:
            self._set_status(f"foobar2000 가져오기 실패: {e}")

    def on_external_message(self, payload: dict) -> None:
        cmd = str(payload.get("cmd", "")).strip().lower()

        if cmd == "show":
            self.show_from_tray()
            return

        if cmd == "open":
            paths = normalize_paths(payload.get("paths", []))
            self.on_external_open_paths(paths)

    def on_external_open_paths(self, paths: List[str]) -> None:
        rows = self._append_paths(normalize_paths(paths))
        if not rows:
            return
        for r in rows:
            if 0 <= r < len(self.tracks):
                self.tracks[r].checked = True
                item = self.table.item(r, 0)
                if item is not None:
                    item.setCheckState(Qt.CheckState.Checked)
        self._sync_tracks()
        self._save_playlist_to_disk()
        self._update_header_check_state()
        play_row = rows[-1]
        self.play_row(play_row)

    def on_table_item_changed(self, item: QTableWidgetItem) -> None:
        if self.table_updating:
            return
        row = item.row()
        col = item.column()
        if not (0 <= row < len(self.tracks)):
            return
        if col == 0:
            self.tracks[row].checked = (item.checkState() == Qt.CheckState.Checked)
            self._sync_tracks()
            self._save_playlist_to_disk()
            self._update_header_check_state()

    def _on_header_check_changed(self, state: Qt.CheckState) -> None:
        checked = state == Qt.CheckState.Checked
        self.table_updating = True
        for i, track in enumerate(self.tracks):
            track.checked = checked
            item = self.table.item(i, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.table_updating = False
        self._sync_tracks()
        self._save_playlist_to_disk()

    def _update_header_check_state(self) -> None:
        if not self.tracks:
            self.check_header.set_check_state(Qt.CheckState.Unchecked)
            return
        checked_count = sum(1 for t in self.tracks if t.checked)
        if checked_count == 0:
            self.check_header.set_check_state(Qt.CheckState.Unchecked)
        elif checked_count == len(self.tracks):
            self.check_header.set_check_state(Qt.CheckState.Checked)
        else:
            self.check_header.set_check_state(Qt.CheckState.PartiallyChecked)

    def on_table_double_clicked(self, row: int, col: int) -> None:
        _ = col
        if not self.tracks[row].checked:
            self.tracks[row].checked = True
            item = self.table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Checked)
            self._sync_tracks()
            self._save_playlist_to_disk()
        self.play_row(row)

    def on_table_context_menu(self, pos: QPoint) -> None:
        row = self.table.rowAt(pos.y())

        menu = QMenu(self)

        if row >= 0:
            self.table.selectRow(row)
            act_open_folder = QAction("폴더 열기", self)
            act_open_folder.triggered.connect(lambda: self._open_track_folder(row))
            menu.addAction(act_open_folder)
            act_edit = QAction("태그 편집", self)
            act_delete = QAction("삭제", self)
            act_edit.triggered.connect(self.on_edit_selected_tags)
            act_delete.triggered.connect(self.on_remove_selected)
            menu.addAction(act_edit)
            menu.addAction(act_delete)
            menu.addSeparator()

        act_add = QAction("파일 추가", self)
        act_add.triggered.connect(self.on_add_files)
        menu.addAction(act_add)

        act_foobar = QAction("foobar2000 가져오기", self)
        act_foobar.triggered.connect(self.on_import_foobar2000)
        menu.addAction(act_foobar)

        vp = self.table.viewport()
        if vp:
            menu.exec(vp.mapToGlobal(pos))

    def _on_search_changed(self, text: str) -> None:
        keyword = text.strip().lower()
        for row in range(self.table.rowCount()):
            if not keyword:
                self.table.setRowHidden(row, False)
            else:
                track = self.tracks[row] if row < len(self.tracks) else None
                if track:
                    match = keyword in track.title.lower() or keyword in track.artist.lower()
                    self.table.setRowHidden(row, not match)
                else:
                    self.table.setRowHidden(row, True)

    def _open_track_folder(self, row: int) -> None:
        if not (0 <= row < len(self.tracks)):
            return
        path = os.path.normpath(self.tracks[row].path)
        if os.path.exists(path):
            import subprocess
            subprocess.Popen(["explorer", "/select,", path])

    def on_delete_selected(self) -> None:
        sm = self.table.selectionModel()
        if sm is None:
            return
        rows = sorted({idx.row() for idx in sm.selectedRows()})
        if not rows:
            return
        count = len(rows)
        reply = QMessageBox.question(
            self, "삭제 확인",
            f"선택한 {count}개 항목을 재생목록에서 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.on_remove_selected()

    def on_remove_selected(self) -> None:
        sm = self.table.selectionModel()
        if sm is None:
            return
        rows = sorted({idx.row() for idx in sm.selectedRows()}, reverse=True)
        if not rows:
            return

        removed = sorted(rows)
        for row in rows:
            if 0 <= row < len(self.tracks):
                self.tracks.pop(row)

        self._rebuild_table()
        self._reindex_after_remove(removed)
        self._save_playlist_to_disk()
        self._set_status(f"{len(removed)}개 파일 삭제")

    def on_edit_selected_tags(self) -> None:
        row = self.table.currentRow()
        if not (0 <= row < len(self.tracks)):
            return

        track = self.tracks[row]
        dlg = TagEditDialog(track, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        title, artist, album = dlg.values()

        try:
            write_audio_metadata(track.path, title, artist, album)
            self._refresh_track_metadata(row)
            self._set_status("태그 저장 완료")
        except Exception as e:
            QMessageBox.critical(self, "태그 저장 오류", str(e))
            self._set_status(f"태그 저장 실패: {e}")

    def on_mode_changed(self, index: int) -> None:
        mode = self.cmb_mode.itemData(index)
        if isinstance(mode, PlayMode):
            self.controller.set_mode(mode)
            self._set_status(f"재생모드: {self.cmb_mode.currentText()}")
            self._save_settings()

    def on_progress_pressed(self) -> None:
        self.user_dragging_progress = True

    def on_progress_released(self) -> None:
        self.user_dragging_progress = False
        self.engine.set_position(self.sld_progress.value())

    def _on_position_changed(self, pos_ms: int) -> None:
        if not self.user_dragging_progress:
            self.sld_progress.blockSignals(True)
            self.sld_progress.setValue(pos_ms)
            self.sld_progress.blockSignals(False)

        self.lbl_time.setText(f"{format_ms(pos_ms)} / {format_ms(self.current_duration_ms)}")

        if self.chk_ab.isChecked():
            a = self.sld_a.value()
            b = self.sld_b.value()
            if b > a and pos_ms >= b:
                self.engine.set_position(a)

    def _on_duration_changed(self, dur_ms: int) -> None:
        self.current_duration_ms = max(0, int(dur_ms))

        idx = self.controller.current_index
        if idx is not None and 0 <= idx < len(self.tracks):
            track = self.tracks[idx]
            if track.duration_ms == 0 and self.current_duration_ms > 0:
                track.duration_ms = self.current_duration_ms
                dur_item = self.table.item(idx, 3)
                if dur_item is not None:
                    dur_item.setText(format_ms(self.current_duration_ms))
                self._save_playlist_to_disk()
        self.sld_progress.setRange(0, self.current_duration_ms)
        self.lbl_time.setText(f"{format_ms(self.sld_progress.value())} / {format_ms(self.current_duration_ms)}")

        self.sld_a.setRange(0, self.current_duration_ms)
        self.sld_b.setRange(0, self.current_duration_ms)

        if self.pending_ab_reset:
            self.sld_a.setValue(0)
            self.sld_b.setValue(self.current_duration_ms)
            self.pending_ab_reset = False
        else:
            if self.sld_a.value() > self.current_duration_ms:
                self.sld_a.setValue(0)
            if self.sld_b.value() > self.current_duration_ms:
                self.sld_b.setValue(self.current_duration_ms)

        self._update_ab_edits()

    def _update_ab_edits(self) -> None:
        self.ed_a.setText(format_ms_detail(self.sld_a.value()))
        self.ed_b.setText(format_ms_detail(self.sld_b.value()))

    def on_a_slider_changed(self, value: int) -> None:
        if value >= self.sld_b.value():
            new_a = max(0, self.sld_b.value() - 1)
            self.sld_a.blockSignals(True)
            self.sld_a.setValue(new_a)
            self.sld_a.blockSignals(False)
        self._update_ab_edits()

    def on_b_slider_changed(self, value: int) -> None:
        if value <= self.sld_a.value():
            new_b = min(self.current_duration_ms, self.sld_a.value() + 1)
            self.sld_b.blockSignals(True)
            self.sld_b.setValue(new_b)
            self.sld_b.blockSignals(False)
        self._update_ab_edits()

    def on_set_a_from_current(self) -> None:
        pos = self.engine.position()
        if pos >= self.sld_b.value():
            pos = max(0, self.sld_b.value() - 1)
        self.sld_a.setValue(pos)
        self._update_ab_edits()

    def on_set_b_from_current(self) -> None:
        pos = self.engine.position()
        if pos <= self.sld_a.value():
            pos = min(self.current_duration_ms, self.sld_a.value() + 1)
        self.sld_b.setValue(pos)
        self._update_ab_edits()

    def play_row(self, row: int) -> None:
        if not (0 <= row < len(self.tracks)):
            return

        track = self.tracks[row]
        if not os.path.isfile(track.path):
            QMessageBox.warning(self, "파일 없음", f"파일을 찾을 수 없습니다.\n{track.path}")
            return

        self.controller.set_current_index(row, push_history=True)
        self.pending_ab_reset = True
        self.engine.play_file(track.path)

        self.table.selectRow(row)
        self.lbl_now.setText(f"재생 중: {track.title}")
        self._set_status("재생")
        self.setWindowTitle(f"{track.artist} - {track.title}" if track.artist else track.title)

        if self.tray is not None:
            self.tray.setToolTip(f"{track.artist} - {track.title}" if track.artist else track.title)
            self._set_tray_icon(QStyle.StandardPixmap.SP_MediaPlay)

    def on_play_clicked(self) -> None:
        row = self.table.currentRow()

        if row < 0:
            if self.controller.current_index is not None and self.engine.has_valid_source():
                if self.engine.playback_state() != QMediaPlayer.PlaybackState.PlayingState:
                    self.engine.play()
                    self._set_status("재생")
                return

            if self.tracks:
                row = 0
            else:
                return

        self.play_row(row)

    def on_pause_clicked(self) -> None:
        self.engine.pause()
        self._set_status("일시정지")

    def on_stop_clicked(self) -> None:
        self.engine.stop()
        self._set_status("정지")
        self.setWindowTitle(self._default_title)
        if self.tray is not None:
            self.tray.setToolTip(self._default_title)
            self._set_tray_icon(QStyle.StandardPixmap.SP_MediaStop)

    def on_next_clicked(self) -> None:
        idx = self.controller.choose_next_manual()
        if idx is None:
            self._set_status("다음곡 없음")
            return
        self.play_row(idx)

    def on_prev_clicked(self) -> None:
        idx = self.controller.choose_prev_manual()
        if idx is None:
            self._set_status("이전곡 없음")
            return
        self.play_row(idx)

    def toggle_play_pause(self) -> None:
        state = self.engine.playback_state()

        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.on_pause_clicked()
            return

        if self.controller.current_index is not None and self.engine.has_valid_source():
            self.engine.play()
            self._set_status("재생")
            return

        if self.table.currentRow() >= 0:
            self.play_row(self.table.currentRow())
            return

        if self.tracks:
            self.play_row(0)

    def seek_relative(self, delta_ms: int) -> None:
        if self.current_duration_ms <= 0:
            return

        current = self.engine.position()
        target = current + int(delta_ms)

        if target < 0:
            target = 0
        elif target > self.current_duration_ms:
            target = self.current_duration_ms

        self.engine.set_position(target)

    def _on_track_finished(self) -> None:
        idx = self.controller.choose_next_auto()
        if idx is None:
            self._set_status("재생 종료")
            return
        self.play_row(idx)

    def _on_error_text(self, text: str) -> None:
        self._set_status(f"오류: {text}")
        QMessageBox.critical(self, "재생 오류", text)

    def _on_files_dropped(self, paths: List[str]) -> None:
        valid = normalize_paths(paths)
        if valid:
            rows = self._append_paths(valid)
            self._set_status(f"{len(rows)}개 파일 추가 (드롭)")

    def _on_rows_moved(self, source_rows: List[int], target_row: int) -> None:
        src = sorted(source_rows)
        if not src:
            return

        current_path: Optional[str] = None
        ci = self.controller.current_index
        if ci is not None and 0 <= ci < len(self.tracks):
            current_path = self.tracks[ci].path

        moved = [self.tracks[i] for i in src]
        for i in reversed(src):
            self.tracks.pop(i)

        adjusted = target_row - sum(1 for r in src if r < target_row)
        adjusted = max(0, min(adjusted, len(self.tracks)))
        for i, t in enumerate(moved):
            self.tracks.insert(adjusted + i, t)

        if current_path:
            for i, t in enumerate(self.tracks):
                if t.path == current_path:
                    self.controller.set_current_index(i, push_history=False)
                    break

        self._rebuild_table()
        self._sync_tracks()
        self._save_playlist_to_disk()
        self._set_status("순서 변경됨")


def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName(APP_ORG)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(True)

    incoming_paths = normalize_paths(sys.argv[1:])

    bridge = SingleInstanceBridge(LOCAL_SERVER_NAME)

    if bridge.send_to_existing_instance({
        "cmd": "open" if incoming_paths else "show",
        "paths": incoming_paths,
    }):
        return 0

    if not bridge.start_listening():
        QMessageBox.critical(None, "오류", "단일 인스턴스 서버를 시작하지 못했습니다.")
        return 1

    win = MainWindow()
    bridge.message_received.connect(win.on_external_message)
    win.show()

    if incoming_paths:
        win.on_external_open_paths(incoming_paths)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
