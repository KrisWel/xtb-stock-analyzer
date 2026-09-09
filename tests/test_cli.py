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


def test_map_writes_identity_csv_without_network(tmp_path, sample_records_path, capsys):
    snapshot = tmp_path / "instruments.csv"
    main(
        [
            "fetch",
            "--from-raw",
            str(sample_records_path),
            "--output",
            str(snapshot),
            "--metadata",
            str(tmp_path / "m.json"),
        ]
    )
    capsys.readouterr()

    out = tmp_path / "identity_map.csv"
    exit_code = main(["map", "--snapshot", str(snapshot), "--output", str(out)])

    assert exit_code == 0
    assert out.exists()
    rows = out.read_text(encoding="utf-8").splitlines()
    assert rows[0] == "symbol,ticker,market,currency,yahoo_symbol,isin"
    assert any(row.startswith("CDR.PL,CDR,PL,PLN,CDR.WA,") for row in rows[1:])
    stdout = capsys.readouterr().out
    assert "3 instruments mapped" in stdout
    assert "isin:         0" in stdout
