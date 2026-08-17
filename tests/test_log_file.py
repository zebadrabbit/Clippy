"""The diagnostic log file: DEBUG lands in it, the console never sees DEBUG."""

import logging

import clippy.log as clog


def _fresh_logger(monkeypatch, tmp_path):
    """setup_logging() is once-per-process; reset it so the test can call it."""
    logger = logging.getLogger("clippy")
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
    monkeypatch.setattr(clog, "_logger", None)
    monkeypatch.setenv("CLIPPY_LOG_FILE", str(tmp_path / "logs" / "clippy.log"))
    return clog.setup_logging()


def test_debug_reaches_file_but_not_console(monkeypatch, tmp_path, capsys):
    logger = _fresh_logger(monkeypatch, tmp_path)
    logger.debug("yt-dlp rc=1 socket timeout")
    logger.info("visible line")
    for h in logger.handlers:
        h.flush()

    body = (tmp_path / "logs" / "clippy.log").read_text(encoding="utf-8")
    assert "yt-dlp rc=1 socket timeout" in body
    assert "visible line" in body
    assert "yt-dlp rc=1 socket timeout" not in capsys.readouterr().out


def test_ansi_stripped_from_file(monkeypatch, tmp_path):
    logger = _fresh_logger(monkeypatch, tmp_path)
    logger.info("\x1b[31mred\x1b[0m")
    for h in logger.handlers:
        h.flush()

    body = (tmp_path / "logs" / "clippy.log").read_text(encoding="utf-8")
    assert "\x1b[" not in body and "red" in body


def test_empty_env_disables_file(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPPY_LOG_FILE", "")
    logger = logging.getLogger("clippy")
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
    monkeypatch.setattr(clog, "_logger", None)
    logger = clog.setup_logging()
    assert not any(isinstance(h, logging.FileHandler) for h in logger.handlers)
