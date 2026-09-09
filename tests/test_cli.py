import json

from xtb_analyzer.cli import main


def test_fetch_from_raw_writes_snapshot(tmp_path, sample_records_path, capsys):
    out = tmp_path / "instruments.csv"
    meta = tmp_path / "instruments.meta.json"

    exit_code = main(
        [
            "fetch",
            "--from-raw",
            str(sample_records_path),
            "--output",
            str(out),
            "--metadata",
            str(meta),
        ]
    )

    assert exit_code == 0
    assert out.exists() and meta.exists()
    assert json.loads(meta.read_text())["instruments_kept"] == 3
    assert "kept 3 of 11 records" in capsys.readouterr().out


def test_fetch_without_credentials_exits_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("XTB_USER_ID", raising=False)
    monkeypatch.delenv("XTB_PASSWORD", raising=False)
    monkeypatch.setattr("xtb_analyzer.config.load_dotenv", lambda *a, **k: False)

    assert main(["fetch", "--output", str(tmp_path / "x.csv")]) == 2


def test_show_reads_snapshot(tmp_path, sample_records_path, capsys):
    out = tmp_path / "instruments.csv"
    main(
        [
            "fetch",
            "--from-raw",
            str(sample_records_path),
            "--output",
            str(out),
            "--metadata",
            str(tmp_path / "m.json"),
        ]
    )
    capsys.readouterr()

    assert main(["show", "--snapshot", str(out), "--asset-class", "ETF"]) == 0
    stdout = capsys.readouterr().out
    assert "IUSQ.DE" in stdout
    assert "AAPL.US" not in stdout


def test_inspect_from_raw(sample_records_path, capsys):
    assert main(["inspect", "--from-raw", str(sample_records_path)]) == 0
    stdout = capsys.readouterr().out
    assert "11 raw records" in stdout
    assert "== categoryName" in stdout
