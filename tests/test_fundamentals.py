import json

import pytest

from xtb_analyzer.fundamentals import (
    Fundamentals,
    FundamentalsError,
    SecFactsClient,
    extract_fundamentals,
)


def _usd_entries(*rows):
    """rows: (start, end, val, form, fp, fy) tuples -> XBRL-shaped unit entries."""
    return [
        {"start": start, "end": end, "val": val, "form": form, "fp": fp, "fy": fy}
        for start, end, val, form, fp, fy in rows
    ]


def _facts_payload(**concepts):
    return {"cik": 320193, "entityName": "Test Co", "facts": {"us-gaap": concepts}}


def test_extract_fundamentals_picks_latest_10k_and_prior_year():
    payload = _facts_payload(
        Revenues={
            "units": {
                "USD": _usd_entries(
                    ("2023-10-01", "2024-09-30", 1000, "10-K", "FY", 2024),
                    ("2024-01-01", "2024-03-31", 300, "10-Q", "Q1", 2024),  # ignored: not FY
                    ("2024-10-01", "2025-09-30", 1200, "10-K", "FY", 2025),
                )
            }
        },
        NetIncomeLoss={
            "units": {
                "USD": _usd_entries(
                    ("2023-10-01", "2024-09-30", 100, "10-K", "FY", 2024),
                    ("2024-10-01", "2025-09-30", 150, "10-K", "FY", 2025),
                )
            }
        },
        Assets={"units": {"USD": [{"end": "2025-09-30", "val": 5000}]}},
        Liabilities={"units": {"USD": [{"end": "2025-09-30", "val": 2000}]}},
        StockholdersEquity={"units": {"USD": [{"end": "2025-09-30", "val": 3000}]}},
    )

    result = extract_fundamentals("AAPL.US", 320193, payload)

    assert result.symbol == "AAPL.US"
    assert result.cik == 320193
    assert result.fiscal_year == 2025
    assert result.fiscal_year_end == "2025-09-30"
    assert result.revenue == 1200
    assert result.revenue_prior_year == 1000
    assert result.net_income == 150
    assert result.net_income_prior_year == 100
    assert result.total_assets == 5000
    assert result.total_liabilities == 2000
    assert result.stockholders_equity == 3000


def test_extract_fundamentals_falls_back_across_concept_names():
    payload = _facts_payload(
        RevenueFromContractWithCustomerExcludingAssessedTax={
            "units": {"USD": _usd_entries(("2024-01-01", "2024-12-31", 500, "10-K", "FY", 2024))}
        }
    )

    result = extract_fundamentals("X.US", 1, payload)

    assert result.revenue == 500


def test_extract_fundamentals_prefers_the_current_concept_over_a_stale_one():
    """Regression: a filer can carry a legacy concept (e.g. taxonomy migration)

    alongside its current one. Apple still has 'Revenues' in its facts but
    stopped updating it after FY2018; picking the first present name instead
    of the most recent one silently pairs a 7-year-stale revenue with a
    fresh net income. Verified live 2026-09-16.
    """
    payload = _facts_payload(
        Revenues={
            "units": {"USD": _usd_entries(("2017-10-01", "2018-09-29", 62900, "10-K", "FY", 2018))}
        },
        RevenueFromContractWithCustomerExcludingAssessedTax={
            "units": {"USD": _usd_entries(("2024-09-29", "2025-09-27", 416161, "10-K", "FY", 2025))}
        },
    )

    result = extract_fundamentals("AAPL.US", 320193, payload)

    assert result.revenue == 416161
    assert result.fiscal_year == 2025


def test_extract_fundamentals_tolerates_missing_concepts():
    result = extract_fundamentals("EMPTY.US", 2, _facts_payload())

    assert result.revenue is None
    assert result.net_income is None
    assert result.total_assets is None
    assert result.fiscal_year is None


@pytest.mark.parametrize(
    ("net_income", "revenue", "expected"),
    [(150, 1200, 0.125), (None, 1200, None), (150, 0, None), (150, None, None)],
)
def test_net_margin(net_income, revenue, expected):
    f = Fundamentals(
        symbol="X.US",
        cik=1,
        fiscal_year=None,
        fiscal_year_end=None,
        revenue=revenue,
        revenue_prior_year=None,
        net_income=net_income,
        net_income_prior_year=None,
        gross_profit=None,
        total_assets=None,
        total_liabilities=None,
        stockholders_equity=None,
        eps_diluted=None,
    )
    assert f.net_margin == expected


def test_revenue_growth():
    f = Fundamentals(
        symbol="X.US",
        cik=1,
        fiscal_year=None,
        fiscal_year_end=None,
        revenue=1200,
        revenue_prior_year=1000,
        net_income=None,
        net_income_prior_year=None,
        gross_profit=None,
        total_assets=None,
        total_liabilities=None,
        stockholders_equity=None,
        eps_diluted=None,
    )
    assert f.revenue_growth == pytest.approx(0.2)


def _fake_getter(payload_or_error, status_code=None):
    def getter(url, headers):
        if status_code is not None:
            import urllib.error

            raise urllib.error.HTTPError(url, status_code, "error", {}, None)
        return json.dumps(payload_or_error).encode("utf-8")

    return getter


def test_sec_facts_client_fetches_and_parses():
    payload = _facts_payload()
    client = SecFactsClient(getter=_fake_getter(payload))

    result = client.get_company_facts(320193)

    assert result == payload


def test_sec_facts_client_raises_without_facts_key():
    client = SecFactsClient(getter=_fake_getter({"cik": 1}))

    with pytest.raises(FundamentalsError):
        client.get_company_facts(1)
