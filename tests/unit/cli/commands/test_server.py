"""Unit tests for cli/commands/server.py — Server startup/stop commands."""
from __future__ import annotations

import argparse
import os
import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── PID helpers ──────────────────────────────────────────


class TestPidHelpers:
    @patch("cli.commands.server._get_pid_file")
    def test_write_pid_file(self, mock_get_pid, tmp_path):
        from cli.commands.server import _write_pid_file

        pid_file = tmp_path / "server.pid"
        mock_get_pid.return_value = pid_file

        _write_pid_file()

        assert pid_file.exists()
        assert pid_file.read_text().strip() == str(os.getpid())

    @patch("cli.commands.server._get_pid_file")
    def test_remove_pid_file(self, mock_get_pid, tmp_path):
        from cli.commands.server import _remove_pid_file

        pid_file = tmp_path / "server.pid"
        pid_file.write_text("12345", encoding="utf-8")
        mock_get_pid.return_value = pid_file

        _remove_pid_file()

        assert not pid_file.exists()

    @patch("cli.commands.server._get_pid_file")
    def test_remove_pid_file_missing(self, mock_get_pid, tmp_path):
        from cli.commands.server import _remove_pid_file

        pid_file = tmp_path / "server.pid"
        mock_get_pid.return_value = pid_file

        # Should not raise
        _remove_pid_file()

    @patch("cli.commands.server._get_pid_file")
    def test_read_pid_valid(self, mock_get_pid, tmp_path):
        from cli.commands.server import _read_pid

        pid_file = tmp_path / "server.pid"
        pid_file.write_text("12345", encoding="utf-8")
        mock_get_pid.return_value = pid_file

        assert _read_pid() == 12345

    @patch("cli.commands.server._get_pid_file")
    def test_read_pid_missing(self, mock_get_pid, tmp_path):
        from cli.commands.server import _read_pid

        pid_file = tmp_path / "nonexistent.pid"
        mock_get_pid.return_value = pid_file

        assert _read_pid() is None

    @patch("cli.commands.server._get_pid_file")
    def test_read_pid_invalid(self, mock_get_pid, tmp_path):
        from cli.commands.server import _read_pid

        pid_file = tmp_path / "server.pid"
        pid_file.write_text("not_a_number", encoding="utf-8")
        mock_get_pid.return_value = pid_file

        assert _read_pid() is None

    def test_is_process_alive_current(self):
        from cli.commands.server import _is_process_alive

        # Current process should be alive
        assert _is_process_alive(os.getpid()) is True

    def test_is_process_alive_nonexistent(self):
        from cli.commands.server import _is_process_alive

        # Very high PID that likely doesn't exist
        assert _is_process_alive(999999999) is False


# ── _stop_server ─────────────────────────────────────────


class TestStopServer:
    @patch("cli.commands.server._read_pid", return_value=None)
    def test_no_pid_file(self, mock_pid, capsys):
        from cli.commands.server import _stop_server

        result = _stop_server()
        assert result is True
        assert "not running" in capsys.readouterr().out

    @patch("cli.commands.server._remove_pid_file")
    @patch("cli.commands.server._is_process_alive", return_value=False)
    @patch("cli.commands.server._read_pid", return_value=12345)
    def test_stale_pid(self, mock_pid, mock_alive, mock_remove, capsys):
        from cli.commands.server import _stop_server

        result = _stop_server()
        assert result is True
        assert "Stale" in capsys.readouterr().out

    @patch("cli.commands.server._remove_pid_file")
    @patch("os.kill")
    @patch("cli.commands.server._is_process_alive", side_effect=[True, False])
    @patch("cli.commands.server._read_pid", return_value=12345)
    def test_successful_stop(self, mock_pid, mock_alive, mock_kill, mock_remove, capsys):
        from cli.commands.server import _stop_server

        result = _stop_server()
        assert result is True
        mock_kill.assert_called_once_with(12345, signal.SIGTERM)

    @patch("os.kill", side_effect=ProcessLookupError)
    @patch("cli.commands.server._is_process_alive", return_value=True)
    @patch("cli.commands.server._read_pid", return_value=12345)
    def test_process_already_exited_on_kill(self, mock_pid, mock_alive, mock_kill, capsys):
        from cli.commands.server import _stop_server

        result = _stop_server()
        assert result is True
        assert "already exited" in capsys.readouterr().out

    @patch("os.kill", side_effect=PermissionError)
    @patch("cli.commands.server._is_process_alive", return_value=True)
    @patch("cli.commands.server._read_pid", return_value=12345)
    def test_permission_error(self, mock_pid, mock_alive, mock_kill, capsys):
        from cli.commands.server import _stop_server

        result = _stop_server()
        assert result is False
        assert "Permission denied" in capsys.readouterr().out


# ── cmd_start ────────────────────────────────────────────


class TestCmdStart:
    @patch("cli.commands.server._is_process_alive", return_value=True)
    @patch("cli.commands.server._read_pid", return_value=999)
    def test_already_running(self, mock_pid, mock_alive):
        from cli.commands.server import cmd_start

        args = argparse.Namespace(host="0.0.0.0", port=18500)
        with pytest.raises(SystemExit):
            cmd_start(args)

    @patch("cli.commands.server._remove_pid_file")
    @patch("uvicorn.run")
    @patch("server.app.create_app")
    @patch("core.paths.get_shared_dir", return_value=Path("/tmp/shared"))
    @patch("core.paths.get_persons_dir", return_value=Path("/tmp/persons"))
    @patch("core.init.ensure_runtime_dir")
    @patch("cli.commands.server._write_pid_file")
    @patch("cli.commands.server._is_process_alive", return_value=False)
    @patch("cli.commands.server._read_pid", return_value=999)
    def test_stale_pid_cleanup_and_start(
        self, mock_pid, mock_alive, mock_write_pid,
        mock_ensure, mock_persons, mock_shared, mock_create, mock_uvicorn,
        mock_remove,
    ):
        from cli.commands.server import cmd_start

        mock_app = MagicMock()
        mock_create.return_value = mock_app

        args = argparse.Namespace(host="0.0.0.0", port=18500)
        cmd_start(args)

        mock_uvicorn.assert_called_once_with(
            mock_app, host="0.0.0.0", port=18500, log_level="info"
        )


# ── cmd_serve ────────────────────────────────────────────


class TestCmdServe:
    @patch("cli.commands.server.cmd_start")
    def test_serve_delegates_to_start(self, mock_start):
        from cli.commands.server import cmd_serve

        args = argparse.Namespace(host="0.0.0.0", port=18500)
        cmd_serve(args)
        mock_start.assert_called_once_with(args)


# ── cmd_stop ─────────────────────────────────────────────


class TestCmdStop:
    @patch("cli.commands.server._stop_server", return_value=True)
    def test_stop_success(self, mock_stop):
        from cli.commands.server import cmd_stop

        args = argparse.Namespace()
        cmd_stop(args)

    @patch("cli.commands.server._stop_server", return_value=False)
    def test_stop_failure(self, mock_stop):
        from cli.commands.server import cmd_stop

        args = argparse.Namespace()
        with pytest.raises(SystemExit):
            cmd_stop(args)


# ── cmd_restart ──────────────────────────────────────────


class TestCmdRestart:
    @patch("cli.commands.server.cmd_start")
    @patch("cli.commands.server._clear_pycache", return_value=0)
    @patch("cli.commands.server._stop_server", return_value=True)
    @patch("time.sleep")
    def test_restart_success(self, mock_sleep, mock_stop, mock_clear, mock_start):
        from cli.commands.server import cmd_restart

        args = argparse.Namespace(host="0.0.0.0", port=18500)
        cmd_restart(args)

        mock_stop.assert_called_once()
        mock_start.assert_called_once_with(args)

    @patch("cli.commands.server._stop_server", return_value=False)
    def test_restart_stop_fails(self, mock_stop):
        from cli.commands.server import cmd_restart

        args = argparse.Namespace(host="0.0.0.0", port=18500)
        with pytest.raises(SystemExit):
            cmd_restart(args)


# ── Deprecated commands ──────────────────────────────────


class TestDeprecatedCommands:
    def test_gateway_deprecated(self):
        from cli.commands.server import cmd_gateway

        args = argparse.Namespace()
        with pytest.raises(SystemExit):
            cmd_gateway(args)

    def test_worker_deprecated(self):
        from cli.commands.server import cmd_worker

        args = argparse.Namespace()
        with pytest.raises(SystemExit):
            cmd_worker(args)


# ── _clear_pycache ───────────────────────────────────────


class TestClearPycache:
    def test_clear_pycache(self, tmp_path):
        """Verify _clear_pycache removes __pycache__ directories."""
        import shutil

        from cli.commands.server import _clear_pycache

        # _clear_pycache uses Path(__file__) to find the project root.
        # We patch __file__ at the module level to point into tmp_path.
        fake_server_py = tmp_path / "cli" / "commands" / "server.py"
        fake_server_py.parent.mkdir(parents=True, exist_ok=True)
        fake_server_py.touch()

        # Create __pycache__ dirs under tmp_path (the "project root")
        cache1 = tmp_path / "src" / "__pycache__"
        cache1.mkdir(parents=True)
        cache2 = tmp_path / "lib" / "__pycache__"
        cache2.mkdir(parents=True)

        import cli.commands.server as server_mod

        original = server_mod.__file__
        try:
            server_mod.__file__ = str(fake_server_py)
            count = _clear_pycache()
            assert count == 2
            assert not cache1.exists()
            assert not cache2.exists()
        finally:
            server_mod.__file__ = original
