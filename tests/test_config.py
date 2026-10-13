import os

from lab2clock.config import load_env


def test_load_env_reads_dotenv_file(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("LAB2CLOCK_TEST_KEY=from-file\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LAB2CLOCK_TEST_KEY", raising=False)

    assert load_env()
    assert os.environ["LAB2CLOCK_TEST_KEY"] == "from-file"
    monkeypatch.delenv("LAB2CLOCK_TEST_KEY")


def test_load_env_does_not_override_existing(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("LAB2CLOCK_TEST_KEY=from-file\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LAB2CLOCK_TEST_KEY", "from-shell")

    load_env()
    assert os.environ["LAB2CLOCK_TEST_KEY"] == "from-shell"
