import json
from pathlib import Path

from xtb_analyzer.cli import main
from xtb_analyzer.fundamentals import Fundamentals
from xtb_analyzer.identity import IdentityMapping
from xtb_analyzer.market_data import Bar
from xtb_analyzer.storage import write_fundamentals, write_identity_map, write_technicals
from xtb_analyzer.technicals import Technicals


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


def test_fetch_sec_writes_snapshot_without_xtb_credentials(tmp_path, monkeypatch, capsys):
    fake_entries = [
        {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    ]
    monkeypatch.setattr("xtb_analyzer.cli.fetch_company_tickers", lambda: fake_entries)

    out = tmp_path / "us_stocks.csv"
    meta = tmp_path / "us_stocks.meta.json"
    cik_out = tmp_path / "us_stocks_cik.csv"
    exit_code = main(
        ["fetch-sec", "--output", str(out), "--metadata", str(meta), "--cik-output", str(cik_out)]
    )

    assert exit_code == 0
    rows = out.read_text(encoding="utf-8").splitlines()
    assert any(row.startswith("AAPL.US,") for row in rows[1:])
    assert json.loads(meta.read_text())["instruments_kept"] == 2
    cik_rows = cik_out.read_text(encoding="utf-8").splitlines()
    assert "AAPL.US,320193" in cik_rows


def test_fetch_gpw_writes_snapshot_with_stocks_and_etfs(tmp_path, monkeypatch, capsys):
    stocks_html = (Path(__file__).parent / "fixtures" / "gpw_stocks_sample.html").read_text(
        encoding="utf-8"
    )
    etf_html = (Path(__file__).parent / "fixtures" / "gpw_etf_sample.html").read_text(
        encoding="utf-8"
    )
    monkeypatch.setattr("xtb_analyzer.cli.fetch_stocks_html", lambda: stocks_html)
    monkeypatch.setattr("xtb_analyzer.cli.fetch_etf_html", lambda: etf_html)

    out = tmp_path / "gpw_instruments.csv"
    meta = tmp_path / "gpw_instruments.meta.json"
    isin_out = tmp_path / "gpw_isin.csv"
    exit_code = main(
        [
            "fetch-gpw",
            "--output",
            str(out),
            "--metadata",
            str(meta),
            "--isin-output",
            str(isin_out),
        ]
    )

    assert exit_code == 0
    rows = out.read_text(encoding="utf-8").splitlines()
    assert any(row.startswith("11B.PL,") for row in rows[1:])
    assert any(row.startswith("ETFBCASH.PL,") for row in rows[1:])
    assert json.loads(meta.read_text())["instruments_kept"] == 5  # 3 stocks + 2 ETFs
    isin_rows = isin_out.read_text(encoding="utf-8").splitlines()
    assert "11B.PL,PL11BTS00015" in isin_rows


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
    assert rows[0] == "symbol,ticker,market,currency,yahoo_symbol,figi"
    assert any(row.startswith("CDR.PL,CDR,PL,PLN,CDR.WA,") for row in rows[1:])
    stdout = capsys.readouterr().out
    assert "3 instruments mapped" in stdout
    assert "figi:         0" in stdout


class _FakeYahooChartClient:
    """Stands in for xtb_analyzer.market_data.YahooChartClient — no network in tests."""

    def __init__(self):
        self.calls = []

    def get_bars(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs))
        return [
            Bar(date="2026-01-01", open=1.0, high=2.0, low=0.5, close=1.5, volume=100),
            Bar(date="2026-01-02", open=1.5, high=2.5, low=1.0, close=2.0, volume=110),
        ]


def test_ohlcv_refreshes_every_mapped_instrument(
    tmp_path, sample_records_path, monkeypatch, capsys
):
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
    identity_map = tmp_path / "identity_map.csv"
    main(["map", "--snapshot", str(snapshot), "--output", str(identity_map)])
    capsys.readouterr()

    fake_client = _FakeYahooChartClient()
    monkeypatch.setattr("xtb_analyzer.cli.YahooChartClient", lambda: fake_client)

    out_dir = tmp_path / "ohlcv"
    exit_code = main(["ohlcv", "--identity-map", str(identity_map), "--output-dir", str(out_dir)])

    assert exit_code == 0
    assert (out_dir / "AAPL.csv").exists()
    assert (out_dir / "CDR.WA.csv").exists()
    assert (out_dir / "IUSQ.DE.csv").exists()
    rows = (out_dir / "AAPL.csv").read_text(encoding="utf-8").splitlines()
    assert rows[0] == "date,open,high,low,close,volume"
    assert len(rows) == 3  # header + 2 bars
    stdout = capsys.readouterr().out
    assert "3/3 instruments refreshed, 0 failed, 0 skipped" in stdout

    # a second run should request an incremental window, not a fresh range
    fake_client.calls.clear()
    main(["ohlcv", "--identity-map", str(identity_map), "--output-dir", str(out_dir)])
    symbol, kwargs = fake_client.calls[0]
    assert "period1" in kwargs and "period2" in kwargs


class _FakeSecFactsClient:
    """Stands in for xtb_analyzer.fundamentals.SecFactsClient — no network in tests."""

    def __init__(self):
        self.calls = []

    def get_company_facts(self, cik):
        self.calls.append(cik)
        return {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {
                                    "start": "2024-01-01",
                                    "end": "2024-12-31",
                                    "val": 1000,
                                    "form": "10-K",
                                    "fp": "FY",
                                    "fy": 2024,
                                }
                            ]
                        }
                    }
                }
            }
        }


def test_fundamentals_writes_csv_for_every_cik(tmp_path, monkeypatch, capsys):
    cik_map = tmp_path / "us_stocks_cik.csv"
    cik_map.write_text("symbol,cik\nAAPL.US,320193\nMSFT.US,789019\n", encoding="utf-8")

    fake_client = _FakeSecFactsClient()
    monkeypatch.setattr("xtb_analyzer.cli.SecFactsClient", lambda: fake_client)

    out = tmp_path / "us_stocks_fundamentals.csv"
    exit_code = main(["fundamentals", "--cik-map", str(cik_map), "--output", str(out)])

    assert exit_code == 0
    assert fake_client.calls == [320193, 789019]
    rows = out.read_text(encoding="utf-8").splitlines()
    assert any(row.startswith("AAPL.US,320193,2024,2024-12-31,1000") for row in rows[1:])
    stdout = capsys.readouterr().out
    assert "2/2 fundamentals fetched, 0 failed" in stdout


def test_fundamentals_respects_symbols_filter(tmp_path, monkeypatch):
    cik_map = tmp_path / "us_stocks_cik.csv"
    cik_map.write_text("symbol,cik\nAAPL.US,320193\nMSFT.US,789019\n", encoding="utf-8")

    fake_client = _FakeSecFactsClient()
    monkeypatch.setattr("xtb_analyzer.cli.SecFactsClient", lambda: fake_client)

    out = tmp_path / "us_stocks_fundamentals.csv"
    main(["fundamentals", "--cik-map", str(cik_map), "--output", str(out), "--symbols", "AAPL.US"])

    assert fake_client.calls == [320193]


def test_technicals_computes_for_instruments_with_enough_history(tmp_path, capsys):
    ohlcv_dir = tmp_path / "ohlcv"
    ohlcv_dir.mkdir()
    rows = "date,open,high,low,close,volume\n" + "\n".join(
        f"2026-01-{i + 1:02d},{100 + i},{101 + i},{99 + i},{100 + i},1000" for i in range(25)
    )
    (ohlcv_dir / "AAPL.csv").write_text(rows + "\n", encoding="utf-8")
    short_rows = "date,open,high,low,close,volume\n2026-01-01,10,11,9,10,100\n"
    (ohlcv_dir / "TOO_SHORT.csv").write_text(short_rows, encoding="utf-8")

    out = tmp_path / "technicals.csv"
    exit_code = main(["technicals", "--ohlcv-dir", str(ohlcv_dir), "--output", str(out)])

    assert exit_code == 0
    rows = out.read_text(encoding="utf-8").splitlines()
    assert any(row.startswith("AAPL,") for row in rows[1:])
    assert not any(row.startswith("TOO_SHORT,") for row in rows[1:])
    stdout = capsys.readouterr().out
    assert "1/2 instruments computed, 1 skipped" in stdout


def _technicals_row(symbol: str, **overrides) -> Technicals:
    base = dict(
        symbol=symbol,
        date="2026-09-17",
        close=110.0,
        sma_20=100.0,
        sma_50=100.0,
        sma_200=90.0,
        ema_12=None,
        ema_26=None,
        rsi_14=20.0,
        macd=None,
        macd_signal=None,
        macd_histogram=None,
        bb_upper=None,
        bb_middle=None,
        bb_lower=None,
        atr_14=None,
    )
    base.update(overrides)
    return Technicals(**base)


def test_score_computes_verdicts_from_technicals_only(tmp_path, capsys):
    technicals_csv = tmp_path / "technicals.csv"
    write_technicals(
        [
            _technicals_row("BULLISH.PL"),
            _technicals_row(
                "BEARISH.PL", close=80.0, sma_20=90.0, sma_50=90.0, sma_200=100.0, rsi_14=80.0
            ),
        ],
        technicals_csv,
    )
    out = tmp_path / "scores.csv"

    exit_code = main(["score", "--technicals", str(technicals_csv), "--output", str(out)])

    assert exit_code == 0
    rows = out.read_text(encoding="utf-8").splitlines()
    assert any(row.startswith("BULLISH.PL,") and ",BUY," in row for row in rows[1:])
    assert any(row.startswith("BEARISH.PL,") and ",SELL," in row for row in rows[1:])
    stdout = capsys.readouterr().out
    assert "2 instruments scored (0 with fundamentals blended in)" in stdout


def test_score_blends_fundamentals_when_identity_map_bridges_the_symbols(tmp_path, capsys):
    technicals_csv = tmp_path / "technicals.csv"
    write_technicals([_technicals_row("AAPL")], technicals_csv)

    fundamentals_csv = tmp_path / "fundamentals.csv"
    write_fundamentals(
        [
            Fundamentals(
                symbol="AAPL.US",
                cik=320193,
                fiscal_year=2025,
                fiscal_year_end="2025-09-27",
                revenue=1000.0,
                revenue_prior_year=800.0,
                net_income=200.0,
                net_income_prior_year=None,
                gross_profit=None,
                total_assets=None,
                total_liabilities=400.0,
                stockholders_equity=500.0,
                eps_diluted=None,
            )
        ],
        fundamentals_csv,
    )

    identity_map_csv = tmp_path / "identity_map.csv"
    write_identity_map(
        [
            IdentityMapping(
                symbol="AAPL.US",
                ticker="AAPL",
                market="US",
                currency="USD",
                yahoo_symbol="AAPL",
                figi=None,
            )
        ],
        identity_map_csv,
    )

    out = tmp_path / "scores.csv"
    exit_code = main(
        [
            "score",
            "--technicals",
            str(technicals_csv),
            "--fundamentals",
            str(fundamentals_csv),
            "--identity-map",
            str(identity_map_csv),
            "--output",
            str(out),
        ]
    )

    assert exit_code == 0
    rows = out.read_text(encoding="utf-8").splitlines()
    assert any(row.startswith("AAPL,") and ",BUY," in row for row in rows[1:])
    stdout = capsys.readouterr().out
    assert "1 instruments scored (1 with fundamentals blended in)" in stdout
