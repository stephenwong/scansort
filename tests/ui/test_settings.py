"""Unit tests for scansort.ui.settings module."""

import contextlib
import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scansort.core.config import AppConfig
from scansort.ui.settings import SettingsDialog


@pytest.fixture
def tk_root():
    """Create a headless root Tkinter instance and destroy it after test."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip("Tkinter display not available")
    yield root
    with contextlib.suppress(tk.TclError):
        root.destroy()


def test_settings_dialog_initialization(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Documents"
    inbox.mkdir()
    docs.mkdir()

    cfg = AppConfig(
        watch_folder=inbox,
        documents_root=docs,
        fallback_folder="_Review_Needed",
        gemini_model="gemini-3.1-flash-lite",
        dry_run=True,
    )

    with (
        patch(
            "scansort.ui.settings.get_api_key",
            return_value="AIzaSyDummyKey1234567890abcdef",
        ),
        patch("scansort.ui.settings.is_autorun_enabled", return_value=True),
        patch("scansort.ui.settings.is_context_menu_enabled", return_value=True),
    ):
        dialog = SettingsDialog(master=tk_root, config=cfg)

        assert dialog.watch_var.get() == str(inbox)
        assert dialog.docs_var.get() == str(docs)
        assert dialog.model_var.get() == "gemini-3.1-flash-lite"
        assert dialog.fallback_var.get() == "_Review_Needed"
        assert dialog.dry_run_var.get() is True
        assert dialog.autorun_var.get() is True
        assert dialog.context_menu_var.get() is True
        dialog.destroy()


def test_settings_dialog_treeview_population(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Documents"
    (docs / "Finances" / "Banking").mkdir(parents=True)
    inbox.mkdir()

    cfg = AppConfig(watch_folder=inbox, documents_root=docs)

    dialog = SettingsDialog(master=tk_root, config=cfg)
    dialog.refresh_taxonomy_tree()

    # Verify root nodes in Treeview
    children = dialog.tree.get_children()
    assert len(children) >= 1
    dialog.destroy()


def test_settings_dialog_save_success(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Documents"
    inbox.mkdir()
    docs.mkdir()

    cfg = AppConfig(watch_folder=inbox, documents_root=docs)
    on_applied_mock = MagicMock()

    with (
        patch("scansort.ui.settings.save_config") as mock_save_cfg,
        patch("scansort.ui.settings.set_api_key") as mock_set_key,
        patch("scansort.ui.settings.enable_autorun") as mock_enable_autorun,
        patch("scansort.ui.settings.show_toast") as mock_toast,
    ):
        dialog = SettingsDialog(master=tk_root, config=cfg, on_applied=on_applied_mock)
        dialog.api_key_var.set("AIzaSyNewKeyUpdated1234567890abcdef")
        dialog.autorun_var.set(True)
        dialog.dry_run_var.set(False)

        dialog.on_save()

        mock_set_key.assert_called_once_with("AIzaSyNewKeyUpdated1234567890abcdef")
        mock_save_cfg.assert_called_once()
        mock_enable_autorun.assert_called_once()
        on_applied_mock.assert_called_once()
        mock_toast.assert_called_once()


def test_settings_dialog_save_validation_error(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()

    # Same folder for watch and docs (illegal)
    cfg = AppConfig(watch_folder=inbox, documents_root=tmp_path / "Docs")

    with patch("tkinter.messagebox.showerror") as mock_error:
        dialog = SettingsDialog(master=tk_root, config=cfg)
        dialog.docs_var.set(str(inbox))  # illegal: same as watch folder

        dialog.on_save()
        mock_error.assert_called_once()
        dialog.destroy()


def test_settings_dialog_toggle_show_key(tk_root, tmp_path: Path):
    cfg = AppConfig(watch_folder=tmp_path / "Inbox", documents_root=tmp_path / "Docs")
    dialog = SettingsDialog(master=tk_root, config=cfg)
    assert dialog.key_entry.cget("show") == "*"
    dialog.show_key_var.set(True)
    dialog._toggle_show_key()
    assert dialog.key_entry.cget("show") == ""
    dialog.show_key_var.set(False)
    dialog._toggle_show_key()
    assert dialog.key_entry.cget("show") == "*"
    dialog.destroy()


def test_settings_dialog_browse_buttons(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()

    cfg = AppConfig(watch_folder=inbox, documents_root=docs)
    dialog = SettingsDialog(master=tk_root, config=cfg)

    new_inbox = tmp_path / "NewInbox"
    new_inbox.mkdir()
    with patch("tkinter.filedialog.askdirectory", return_value=str(new_inbox)):
        dialog._browse_watch_folder()
        assert dialog.watch_var.get() == str(new_inbox)

    new_docs = tmp_path / "NewDocs"
    new_docs.mkdir()
    with patch("tkinter.filedialog.askdirectory", return_value=str(new_docs)):
        dialog._browse_docs_folder()
        assert dialog.docs_var.get() == str(new_docs)

    dialog.destroy()


def test_settings_dialog_save_key_and_config_errors(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)

    # 1. API key error
    with (
        patch("tkinter.messagebox.showerror") as mock_error,
        patch("scansort.ui.settings.set_api_key", side_effect=OSError("Vault locked")),
    ):
        dialog = SettingsDialog(master=tk_root, config=cfg)
        dialog.api_key_var.set("AIzaSyTestKey1234567890abcdef")
        dialog.on_save()
        mock_error.assert_called_once()
        dialog.destroy()

    # 2. Config save error
    with (
        patch("tkinter.messagebox.showerror") as mock_error,
        patch("scansort.ui.settings.save_config", side_effect=OSError("Disk full")),
    ):
        dialog = SettingsDialog(master=tk_root, config=cfg)
        dialog.on_save()
        mock_error.assert_called_once()
        dialog.destroy()


def test_settings_dialog_disable_autorun(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)

    with (
        patch("scansort.ui.settings.save_config") as mock_save,
        patch("scansort.ui.settings.disable_autorun") as mock_disable,
        patch("scansort.ui.settings.show_toast"),
    ):
        dialog = SettingsDialog(master=tk_root, config=cfg)
        dialog.autorun_var.set(False)
        dialog.on_save()
        mock_disable.assert_called_once()
        mock_save.assert_called_once()
        assert mock_save.call_args[0][0].start_on_boot is False


def test_open_settings_dialog_singleton(tmp_path: Path):
    import scansort.ui.settings as settings_mod
    from scansort.ui.settings import open_settings_dialog

    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)

    dialog1 = open_settings_dialog(config=cfg)
    assert dialog1 is not None
    assert settings_mod._ACTIVE_DIALOG_INSTANCE is dialog1

    # Second call reuses and focuses the same instance
    dialog2 = open_settings_dialog(config=cfg)
    assert dialog2 is dialog1

    dialog1.destroy()
    assert settings_mod._ACTIVE_DIALOG_INSTANCE is None


def test_register_or_existing_discards_racing_loser(tk_root, tmp_path: Path):
    """A dialog constructed during a race is discarded for the live instance."""
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)

    winner = SettingsDialog(master=tk_root, config=cfg)
    SettingsDialog._set_instance(winner)
    loser = SettingsDialog(master=tk_root, config=cfg)

    result = SettingsDialog.register_or_existing(loser)

    assert result is winner
    assert not loser.winfo_exists()
    winner.destroy()


def test_settings_dialog_rejects_empty_paths(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)

    dialog = SettingsDialog(master=tk_root, config=cfg)
    with patch("tkinter.messagebox.showerror") as mock_error:
        # Empty watch folder
        dialog.watch_var.set("   ")
        dialog.on_save()
        mock_error.assert_called_once()
        assert "Drop Folder" in mock_error.call_args[0][1]

        mock_error.reset_mock()
        # Reset watch, empty docs root
        dialog.watch_var.set(str(inbox))
        dialog.docs_var.set("")
        dialog.on_save()
        mock_error.assert_called_once()
        assert "Documents Destination Root" in mock_error.call_args[0][1]
    dialog.destroy()


def test_settings_dialog_context_menu_toggle(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)

    with (
        patch("scansort.ui.settings.save_config"),
        patch("scansort.ui.settings.enable_context_menu") as mock_enable,
        patch("scansort.ui.settings.disable_context_menu") as mock_disable,
        patch("scansort.ui.settings.show_toast"),
    ):
        dialog = SettingsDialog(master=tk_root, config=cfg)

        # Enable context menu
        dialog.context_menu_var.set(True)
        dialog.on_save()
        mock_enable.assert_called_once()

        # Disable context menu
        dialog = SettingsDialog(master=tk_root, config=cfg)
        dialog.context_menu_var.set(False)
        dialog.on_save()
        mock_disable.assert_called_once()


def test_settings_dialog_context_menu_failure_toast(tk_root, tmp_path: Path):
    """A failed context-menu toggle surfaces to the user instead of a plain success toast."""
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)

    with (
        patch("scansort.ui.settings.save_config"),
        patch("scansort.ui.settings.enable_context_menu", return_value=False),
        patch("scansort.ui.settings.show_toast") as mock_toast,
    ):
        dialog = SettingsDialog(master=tk_root, config=cfg)
        dialog.context_menu_var.set(True)
        dialog.on_save()
        dialog.destroy()

    messages = " | ".join(str(c.args[1]) for c in mock_toast.call_args_list)
    assert "could not be updated" in messages


def test_settings_dialog_ocr_toggles(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)

    with (
        patch("scansort.ui.settings.save_config") as mock_save,
        patch("scansort.ui.settings.enable_ocr_menu") as mock_enable,
        patch("scansort.ui.settings.is_ocr_menu_enabled", return_value=False),
        patch("scansort.ui.settings.is_context_menu_enabled", return_value=False),
        patch("scansort.ui.settings.disable_context_menu"),
        patch("scansort.ui.settings.is_autorun_enabled", return_value=False),
        patch("scansort.ui.settings.disable_autorun"),
        patch("scansort.ui.settings.show_toast"),
    ):
        dialog = SettingsDialog(master=tk_root, config=cfg)
        dialog.ocr_var.set(True)
        dialog.ocr_menu_var.set(True)
        dialog.on_save()

    mock_enable.assert_called_once()
    assert mock_save.call_args.args[0].ocr_enabled is True


def test_settings_dialog_ocr_menu_disable_when_enabled(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)

    with (
        patch("scansort.ui.settings.save_config"),
        patch("scansort.ui.settings.disable_ocr_menu") as mock_disable,
        patch("scansort.ui.settings.is_ocr_menu_enabled", return_value=True),
        patch("scansort.ui.settings.is_context_menu_enabled", return_value=False),
        patch("scansort.ui.settings.disable_context_menu"),
        patch("scansort.ui.settings.is_autorun_enabled", return_value=False),
        patch("scansort.ui.settings.disable_autorun"),
        patch("scansort.ui.settings.show_toast"),
    ):
        dialog = SettingsDialog(master=tk_root, config=cfg)
        dialog.ocr_menu_var.set(False)
        dialog.on_save()

    mock_disable.assert_called_once()


def test_settings_dialog_open_drop_zone(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)

    dialog = SettingsDialog(master=tk_root, config=cfg)
    with patch("scansort.ui.drop_zone.open_drop_zone_window") as mock_open:
        dialog._open_drop_zone()
        mock_open.assert_called_once_with(master=dialog, config=dialog.app_config)
    dialog.destroy()


def test_settings_autorun_failure_reconciles_saved_flag(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)

    with (
        patch("scansort.ui.settings.save_config") as mock_save,
        patch("scansort.ui.settings.enable_autorun", return_value=False),
        patch("scansort.ui.settings.is_autorun_enabled", return_value=False),
        patch("scansort.ui.settings.show_toast"),
    ):
        dialog = SettingsDialog(master=tk_root, config=cfg)
        dialog.autorun_var.set(True)
        dialog.on_save()

    saved_cfgs = [call.args[0] for call in mock_save.call_args_list]
    assert saved_cfgs[-1].start_on_boot is False


def test_open_settings_dialog_after_dead_instance(tmp_path: Path):
    import tkinter as tk

    import scansort.ui.settings as settings_mod
    from scansort.ui.settings import open_settings_dialog

    dead = MagicMock()
    dead.winfo_exists.side_effect = tk.TclError("application has been destroyed")
    settings_mod._ACTIVE_DIALOG_INSTANCE = dead

    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)

    dialog = open_settings_dialog(config=cfg)
    assert dialog is not dead
    assert settings_mod._ACTIVE_DIALOG_INSTANCE is dialog
    dialog.destroy()


def test_settings_destroy_twice_is_safe(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)
    dialog = SettingsDialog(master=tk_root, config=cfg)
    dialog.destroy()
    dialog.destroy()


def _doctor_report():
    from scansort.classification.doctor import (
        ACTION_CREATE_FOLDER,
        ACTION_NONE,
        KIND_OVERBROAD_FOLDER,
        KIND_REVIEW_CLUSTER,
        SEVERITY_LOW,
        SEVERITY_MEDIUM,
        DoctorFinding,
        DoctorReport,
    )

    return DoctorReport(
        folders=["Misc"],
        findings=[
            DoctorFinding(
                kind=KIND_REVIEW_CLUSTER,
                severity=SEVERITY_MEDIUM,
                message="Recurring theme 'Pet_Insurance'",
                action=ACTION_CREATE_FOLDER,
                target_folder="Pet_Insurance",
                keywords=["pet"],
            ),
            DoctorFinding(
                kind=KIND_OVERBROAD_FOLDER,
                severity=SEVERITY_LOW,
                message="Over-broad folder 'Misc'",
                action=ACTION_NONE,
                primary_folder="Misc",
            ),
        ],
    )


def test_settings_dialog_doctor_run_populate_and_dismiss(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)
    dialog = SettingsDialog(master=tk_root, config=cfg)

    with patch("scansort.ui.settings.run_doctor", return_value=_doctor_report()):
        dialog.run_taxonomy_doctor()

    assert len(dialog._doctor_findings) == 2
    assert len(dialog.doctor_tree.get_children()) == 2

    dialog.doctor_tree.selection_set("0")
    dialog.dismiss_selected_doctor_finding()
    assert len(dialog._doctor_findings) == 1
    assert len(dialog.doctor_tree.get_children()) == 1
    dialog.destroy()


def test_settings_dialog_doctor_approve_action(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)
    dialog = SettingsDialog(master=tk_root, config=cfg)

    with (
        patch("scansort.ui.settings.run_doctor", return_value=_doctor_report()),
        patch(
            "scansort.ui.settings.apply_doctor_action",
            return_value="Created destination folder 'Pet_Insurance'",
        ) as mock_apply,
        patch("scansort.ui.settings.show_toast") as mock_toast,
    ):
        dialog.run_taxonomy_doctor()
        dialog.doctor_tree.selection_set("0")
        dialog.approve_selected_doctor_finding()

    mock_apply.assert_called_once()
    assert mock_apply.call_args.args[0].target_folder == "Pet_Insurance"
    mock_toast.assert_called_once()
    dialog.destroy()


def test_settings_dialog_doctor_approve_without_selection(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)
    dialog = SettingsDialog(master=tk_root, config=cfg)

    with patch("tkinter.messagebox.showinfo") as mock_info:
        dialog.approve_selected_doctor_finding()
    mock_info.assert_called_once()
    dialog.destroy()


def test_settings_dialog_doctor_run_error_surfaces(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)
    dialog = SettingsDialog(master=tk_root, config=cfg)

    with (
        patch("scansort.ui.settings.run_doctor", side_effect=ValueError("bad root")),
        patch("tkinter.messagebox.showerror") as mock_error,
    ):
        dialog.run_taxonomy_doctor()
    mock_error.assert_called_once()
    dialog.destroy()


def test_open_settings_dialog_doctor_runs_analysis(tk_root, tmp_path: Path):
    from scansort.ui.settings import open_settings_dialog

    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)

    with patch(
        "scansort.ui.settings.run_doctor", return_value=_doctor_report()
    ) as mock_run:
        dialog = open_settings_dialog(config=cfg, doctor=True)
    assert mock_run.call_count == 1
    assert dialog._doctor_findings
    dialog.destroy()


def test_open_settings_dialog_doctor_runs_on_existing_instance(tmp_path: Path):
    from scansort.ui.settings import open_settings_dialog

    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)

    dialog = open_settings_dialog(config=cfg)
    with patch(
        "scansort.ui.settings.run_doctor", return_value=_doctor_report()
    ) as mock_run:
        again = open_settings_dialog(config=cfg, doctor=True)
        assert again is dialog
        # The queued after(0, ...) callback runs when the event loop updates.
        dialog.update()
    assert mock_run.call_count == 1
    dialog.destroy()


def test_settings_dialog_doctor_empty_root_does_not_scan(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)
    dialog = SettingsDialog(master=tk_root, config=cfg)

    dialog.docs_var.set("   ")
    with (
        patch("scansort.ui.settings.run_doctor") as mock_run,
        patch("tkinter.messagebox.showerror") as mock_error,
    ):
        dialog.run_taxonomy_doctor()

    mock_run.assert_not_called()
    mock_error.assert_called_once()
    assert dialog._doctor_findings == []
    assert dialog._doctor_root is None
    dialog.destroy()


def test_settings_dialog_doctor_approve_uses_analyzed_root(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs_a = tmp_path / "DocsA"
    docs_b = tmp_path / "DocsB"
    inbox.mkdir()
    docs_a.mkdir()
    docs_b.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs_a)
    dialog = SettingsDialog(master=tk_root, config=cfg)

    with patch("scansort.ui.settings.run_doctor", return_value=_doctor_report()):
        dialog.run_taxonomy_doctor()

    # The user edits the documents field after the analysis was computed.
    dialog.docs_var.set(str(docs_b))
    dialog.doctor_tree.selection_set("0")
    with patch(
        "scansort.ui.settings.apply_doctor_action", return_value="ok"
    ) as mock_apply:
        dialog.approve_selected_doctor_finding()

    assert mock_apply.call_args.args[1].documents_root == docs_a.resolve()
    dialog.destroy()


def test_settings_dialog_doctor_dismiss_persists_across_rerun(tk_root, tmp_path: Path):
    inbox = tmp_path / "Inbox"
    docs = tmp_path / "Docs"
    inbox.mkdir()
    docs.mkdir()
    cfg = AppConfig(watch_folder=inbox, documents_root=docs)
    dialog = SettingsDialog(master=tk_root, config=cfg)

    with patch("scansort.ui.settings.run_doctor", return_value=_doctor_report()):
        dialog.run_taxonomy_doctor()
    dialog.doctor_tree.selection_set("0")
    dismissed_id = dialog._doctor_findings[0].finding_id
    dialog.dismiss_selected_doctor_finding()

    with patch("scansort.ui.settings.run_doctor", return_value=_doctor_report()):
        dialog.run_taxonomy_doctor()

    assert all(f.finding_id != dismissed_id for f in dialog._doctor_findings)
    dialog.destroy()
