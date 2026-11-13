import os
import sys
from collections import namedtuple
from pathlib import Path
from unittest.mock import MagicMock, patch

from scansort import __version__
from scansort.platform import toasts


def _install_fake_winrt(
    monkeypatch,
) -> tuple[MagicMock, MagicMock, list[MagicMock]]:
    """Inject fake ``winrt`` XML/notification modules and simulate Windows."""
    monkeypatch.setattr("sys.platform", "win32")

    fake_dom = MagicMock()
    created_docs: list[MagicMock] = []

    def _make_doc():
        doc = MagicMock()
        doc.loaded_xml = ""

        def _load_xml(xml_str: str) -> None:
            doc.loaded_xml = xml_str

        doc.load_xml.side_effect = _load_xml
        created_docs.append(doc)
        return doc

    fake_dom.XmlDocument.side_effect = _make_doc

    fake_notif_mod = MagicMock()
    fake_notifier = MagicMock()
    fake_notif_mod.ToastNotificationManager.create_toast_notifier_with_id.return_value = fake_notifier

    created_toasts: list[MagicMock] = []

    def _make_toast(xml_doc):
        toast = MagicMock()
        toast.xml_doc = xml_doc
        toast.activated_handlers = []

        def _add_activated(handler):
            toast.activated_handlers.append(handler)
            return len(toast.activated_handlers)

        toast.add_activated.side_effect = _add_activated
        created_toasts.append(toast)
        return toast

    fake_notif_mod.ToastNotification.side_effect = _make_toast

    class _FakeToastActivatedEventArgs:
        pass

    fake_notif_mod.ToastActivatedEventArgs = _FakeToastActivatedEventArgs

    fake_winrt = MagicMock()
    fake_winrt.windows.data.xml.dom = fake_dom
    fake_winrt.windows.ui.notifications = fake_notif_mod

    toasts._backend = None
    with patch.dict(
        sys.modules,
        {
            "winrt": fake_winrt,
            "winrt.windows": fake_winrt.windows,
            "winrt.windows.data": fake_winrt.windows.data,
            "winrt.windows.data.xml": fake_winrt.windows.data.xml,
            "winrt.windows.data.xml.dom": fake_dom,
            "winrt.windows.ui": fake_winrt.windows.ui,
            "winrt.windows.ui.notifications": fake_notif_mod,
        },
    ):
        yield fake_dom, fake_notif_mod, fake_notifier, created_toasts
    toasts._backend = None


def test_show_toast_noop_off_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    assert toasts.show_toast("ScanSort updated", "body") is False


def test_show_toast_builds_backend_and_displays(monkeypatch):
    for _, fake_notif_mod, fake_notifier, created_toasts in _install_fake_winrt(
        monkeypatch
    ):
        assert (
            toasts.show_toast(
                "ScanSort update available", f"Version {__version__} found & ready."
            )
            is True
        )
        fake_notif_mod.ToastNotificationManager.create_toast_notifier_with_id.assert_called_once_with(
            r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\cmd.exe"
        )
        assert len(created_toasts) == 1
        toast = created_toasts[0]
        xml = toast.xml_doc.loaded_xml
        assert "<text>ScanSort update available</text>" in xml
        assert f"<text>Version {__version__} found &amp; ready.</text>" in xml
        assert '<text placement="attribution">ScanSort</text>' in xml
        fake_notifier.show.assert_called_once_with(toast)


def test_show_toast_swallows_missing_library(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    toasts._backend = None
    try:
        with patch.dict(
            sys.modules,
            {
                "winrt.windows.data.xml.dom": None,
                "winrt.windows.ui.notifications": None,
            },
        ):
            assert toasts.show_toast("t", "b") is False
    finally:
        toasts._backend = None


def test_show_toast_swallows_display_failure(monkeypatch):
    for _, _, fake_notifier, _ in _install_fake_winrt(monkeypatch):
        fake_notifier.show.side_effect = OSError("no interactive session")
        assert toasts.show_toast("t", "b") is False


def test_show_toast_reuses_cached_backend(monkeypatch):
    backend = MagicMock()
    toasts._backend = backend
    monkeypatch.setattr("sys.platform", "win32")
    try:
        assert toasts.show_toast("t", "b") is True
        backend.show.assert_called_once_with(
            "t", "b", on_click=None, folder_path=None, log_path=None
        )
    finally:
        toasts._backend = None


def test_open_path_windows_os_startfile(tmp_path: Path, monkeypatch):
    target = tmp_path / "folder"
    target.mkdir()
    mock_startfile = MagicMock()
    monkeypatch.setattr(os, "startfile", mock_startfile, raising=False)
    monkeypatch.setattr("sys.platform", "win32")

    assert toasts.open_path(target) is True
    mock_startfile.assert_called_once_with(str(target.resolve()))


def test_open_path_windows_creates_missing_file_in_existing_parent(
    tmp_path: Path, monkeypatch
):
    log_file = tmp_path / "scansort.log"
    mock_startfile = MagicMock()
    monkeypatch.setattr(os, "startfile", mock_startfile, raising=False)
    monkeypatch.setattr("sys.platform", "win32")

    assert not log_file.exists()
    assert toasts.open_path(log_file, create_file=True) is True
    assert log_file.exists()
    mock_startfile.assert_called_once_with(str(log_file.resolve()))


def test_open_path_nonexistent_parent_returns_false(tmp_path: Path, monkeypatch):
    target = tmp_path / "nonexistent_dir" / "file.log"
    mock_startfile = MagicMock()
    monkeypatch.setattr(os, "startfile", mock_startfile, raising=False)
    monkeypatch.setattr("sys.platform", "win32")

    assert toasts.open_path(target) is False
    mock_startfile.assert_not_called()


def test_open_path_windows_subprocess_fallback(tmp_path: Path, monkeypatch):
    target = tmp_path / "folder"
    target.mkdir()
    if hasattr(os, "startfile"):
        monkeypatch.delattr(os, "startfile")
    monkeypatch.setattr("sys.platform", "win32")

    with patch("subprocess.Popen") as mock_popen:
        assert toasts.open_path(target) is True
        mock_popen.assert_called_once_with(["explorer.exe", str(target.resolve())])


def test_open_path_macos_and_linux(tmp_path: Path, monkeypatch):
    target = tmp_path / "folder"
    target.mkdir()
    if hasattr(os, "startfile"):
        monkeypatch.delattr(os, "startfile")

    monkeypatch.setattr("sys.platform", "darwin")
    with patch("subprocess.Popen") as mock_popen:
        assert toasts.open_path(target) is True
        mock_popen.assert_called_once_with(["open", str(target.resolve())])

    monkeypatch.setattr("sys.platform", "linux")
    with patch("subprocess.Popen") as mock_popen:
        assert toasts.open_path(target) is True
        mock_popen.assert_called_once_with(["xdg-open", str(target.resolve())])


def test_open_path_swallows_launcher_exception(tmp_path: Path, monkeypatch):
    target = tmp_path / "folder"
    target.mkdir()
    mock_startfile = MagicMock(side_effect=OSError("Access denied"))
    monkeypatch.setattr(os, "startfile", mock_startfile, raising=False)
    monkeypatch.setattr("sys.platform", "win32")

    assert toasts.open_path(target) is False


def test_show_toast_interactive_activation(tmp_path: Path, monkeypatch):
    folder = tmp_path / "FiledFolder"
    folder.mkdir()
    log_path = tmp_path / "scansort.log"

    for _, fake_notif_mod, _, created_toasts in _install_fake_winrt(monkeypatch):
        with patch("scansort.platform.toasts.open_path") as mock_open:
            assert (
                toasts.show_toast(
                    "ScanSort",
                    "Filing failed",
                    folder_path=folder,
                    log_path=log_path,
                )
                is True
            )

            toast = created_toasts[0]
            assert (
                '<action content="View Logs" arguments="view_log" activationType="foreground"/>'
                in toast.xml_doc.loaded_xml
            )
            assert len(toast.activated_handlers) == 1
            handler = toast.activated_handlers[0]

            # Simulate PyWinRT Object.as_(ToastActivatedEventArgs) casting
            Args = namedtuple("Args", ["arguments"])

            class _WinrtEventObj:
                def __init__(self, arguments: str, args_cls=Args):
                    self._args = args_cls(arguments=arguments)

                def as_(self, target_cls, expected=fake_notif_mod):
                    assert target_cls is expected.ToastActivatedEventArgs
                    return self._args

            handler(toast, _WinrtEventObj("view_log"))
            mock_open.assert_called_with(log_path, create_file=True)

            mock_open.reset_mock()
            handler(toast, Args(arguments=""))
            mock_open.assert_called_with(folder)


def test_show_toast_retains_recent_toasts_in_memory(monkeypatch):
    for _, _, _, _ in _install_fake_winrt(monkeypatch):
        backend = toasts._get_backend()
        for i in range(25):
            toasts.show_toast("Title", f"Body {i}")
        assert len(backend._recent_toasts) == 20
        assert "<text>Body 24</text>" in backend._recent_toasts[-1].xml_doc.loaded_xml


def test_backend_fallback_when_create_toast_notifier_with_id_missing(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    fake_dom = MagicMock()
    fake_notif_mod = MagicMock()
    fake_notif_mod.ToastNotificationManager = MagicMock(spec=["create_toast_notifier"])
    fake_notifier = (
        fake_notif_mod.ToastNotificationManager.create_toast_notifier.return_value
    )
    fake_winrt = MagicMock()
    fake_winrt.windows.data.xml.dom = fake_dom
    fake_winrt.windows.ui.notifications = fake_notif_mod

    toasts._backend = None
    with patch.dict(
        sys.modules,
        {
            "winrt": fake_winrt,
            "winrt.windows": fake_winrt.windows,
            "winrt.windows.data": fake_winrt.windows.data,
            "winrt.windows.data.xml": fake_winrt.windows.data.xml,
            "winrt.windows.data.xml.dom": fake_dom,
            "winrt.windows.ui": fake_winrt.windows.ui,
            "winrt.windows.ui.notifications": fake_notif_mod,
        },
    ):
        assert toasts.show_toast("Title", "Body") is True
        fake_notif_mod.ToastNotificationManager.create_toast_notifier.assert_called_once_with(
            r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\cmd.exe"
        )
        fake_notifier.show.assert_called_once()
    toasts._backend = None


def test_show_toast_custom_on_click_callback(monkeypatch):
    for _, _, _, created_toasts in _install_fake_winrt(monkeypatch):
        mock_cb = MagicMock()
        assert toasts.show_toast("Title", "Body", on_click=mock_cb) is True
        toast = created_toasts[0]
        assert len(toast.activated_handlers) == 1
        toast.activated_handlers[0](toast, None)
        mock_cb.assert_called_once()


def test_backend_missing_notifier_factory(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    fake_dom = MagicMock()
    fake_notif_mod = MagicMock()
    fake_notif_mod.ToastNotificationManager = MagicMock(spec=[])
    fake_winrt = MagicMock()
    fake_winrt.windows.data.xml.dom = fake_dom
    fake_winrt.windows.ui.notifications = fake_notif_mod
    toasts._backend = None
    with patch.dict(
        sys.modules,
        {
            "winrt": fake_winrt,
            "winrt.windows": fake_winrt.windows,
            "winrt.windows.data": fake_winrt.windows.data,
            "winrt.windows.data.xml": fake_winrt.windows.data.xml,
            "winrt.windows.data.xml.dom": fake_dom,
            "winrt.windows.ui": fake_winrt.windows.ui,
            "winrt.windows.ui.notifications": fake_notif_mod,
        },
    ):
        assert toasts.show_toast("Title", "Body") is False
    toasts._backend = None


def test_show_toast_returns_false_when_toast_class_missing(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    fake_dom = MagicMock()
    fake_notif_mod = MagicMock(spec=["ToastNotificationManager"])
    fake_winrt = MagicMock()
    fake_winrt.windows.data.xml.dom = fake_dom
    fake_winrt.windows.ui.notifications = fake_notif_mod
    toasts._backend = None
    with patch.dict(
        sys.modules,
        {
            "winrt": fake_winrt,
            "winrt.windows": fake_winrt.windows,
            "winrt.windows.data": fake_winrt.windows.data,
            "winrt.windows.data.xml": fake_winrt.windows.data.xml,
            "winrt.windows.data.xml.dom": fake_dom,
            "winrt.windows.ui": fake_winrt.windows.ui,
            "winrt.windows.ui.notifications": fake_notif_mod,
        },
    ):
        assert toasts.show_toast("Title", "Body") is False
    toasts._backend = None


def test_get_backend_constructed_once_under_concurrency(monkeypatch):
    import threading

    built = []

    class _SlowBackend:
        def __init__(self):
            built.append(1)

    monkeypatch.setattr(toasts, "_backend", None)
    monkeypatch.setattr(toasts, "WindowsToastBackend", _SlowBackend)

    threads = [threading.Thread(target=toasts._get_backend) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(built) == 1


def test_open_path_does_not_create_dotted_directory(tmp_path: Path, monkeypatch):
    target = tmp_path / "Thesis.2024"
    monkeypatch.setattr("sys.platform", "linux")
    assert toasts.open_path(target) is False
    assert not target.exists()
