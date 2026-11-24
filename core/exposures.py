"""Seeded look-through exposures (provenance = manual-factsheet-tag).

Real sector (GICS) and country (ISO alpha-2) weight vectors for the core sleeve,
transcribed from factsheet tags with their as-of dates. Weights are fractions of
the fund (0..1). This powers the overlap engine fully offline; name-level
look-through (BlackRock CSV) layers on top when network is available.

SECTORS is intentionally omitted for the Global Aggregate bond fund: ~65% is
government/securitized with no GICS sector (tagging it would be mislabelling).
Country vectors are provided for all six (issuer domicile / listing).
"""
from __future__ import annotations

AS_OF: dict[str, str] = {
    "IE000S3N6R34": "2026-10-30",
    "LU3086269894": "2026-10-30",
    "IE00BMTX1Y45": "2026-11-10",
    "LU0908500753": "2026-11-01",
    "IE00BG47KH54": "2026-09-30",
    "IE00B3F81R35": "2026-11-10",
}

SECTORS: dict[str, dict[str, float]] = {
    # MSCI EM -- ~42% IT = semiconductor-dominated
    "IE000S3N6R34": {
        "Information Technology": 0.4177, "Financials": 0.2044,
        "Consumer Discretionary": 0.0766, "Industrials": 0.0604,
        "Communication Services": 0.0602, "Materials": 0.0577,
        "Energy": 0.0372, "Consumer Staples": 0.0283, "Health Care": 0.0280,
        "Utilities": 0.0193, "Real Estate": 0.0103,
    },
    # MSCI Japan -- Industrials-led diversifier
    "LU3086269894": {
        "Industrials": 0.2425, "Financials": 0.1906,
        "Information Technology": 0.1753, "Consumer Discretionary": 0.1535,
        "Communication Services": 0.0652, "Health Care": 0.0587,
        "Consumer Staples": 0.0388, "Materials": 0.0363,
        "Real Estate": 0.0189, "Energy": 0.0104, "Utilities": 0.0099,
    },
    # S&P 500 -- IT-heavy US large-cap
    "IE00BMTX1Y45": {
        "Information Technology": 0.359, "Financials": 0.127,
        "Health Care": 0.105, "Consumer Discretionary": 0.098,
        "Communication Services": 0.087, "Industrials": 0.083,
        "Consumer Staples": 0.049, "Energy": 0.036, "Utilities": 0.021,
        "Real Estate": 0.018, "Materials": 0.017,
    },
    # STOXX Europe 600 -- Financials-led (ICB mapped to GICS)
    "LU0908500753": {
        "Financials": 0.254, "Industrials": 0.174, "Health Care": 0.130,
        "Information Technology": 0.097, "Consumer Staples": 0.089,
        "Energy": 0.068, "Materials": 0.062, "Consumer Discretionary": 0.060,
        "Utilities": 0.046, "Communication Services": 0.021,
    },
    # iShares Core EUR Corp Bond -- ~37.5% Financials issuance
    "IE00B3F81R35": {
        "Financials": 0.375, "Industrials": 0.097,
        "Consumer Discretionary": 0.094, "Utilities": 0.084,
        "Consumer Staples": 0.074, "Communication Services": 0.069,
        "Health Care": 0.062, "Real Estate": 0.050, "Other": 0.037,
        "Energy": 0.029, "Materials": 0.029,
    },
}

COUNTRIES: dict[str, dict[str, float]] = {
    "IE000S3N6R34": {
        "TW": 0.298, "KR": 0.218, "CN": 0.196, "IN": 0.100, "ZA": 0.023,
        "BR": 0.022, "SA": 0.018, "MX": 0.016, "ID": 0.015, "MY": 0.014,
        "AE": 0.013, "TH": 0.013, "PL": 0.010, "QA": 0.008, "KW": 0.008,
        "PH": 0.006, "GR": 0.005, "CL": 0.005, "TR": 0.004, "HU": 0.002,
        "PE": 0.002, "CZ": 0.001, "EG": 0.001, "CO": 0.001,
    },
    "LU3086269894": {"JP": 1.0},
    "IE00BMTX1Y45": {"US": 1.0},
    "LU0908500753": {
        "GB": 0.223, "CH": 0.154, "FR": 0.132, "DE": 0.131, "NL": 0.091,
        "ES": 0.055, "IT": 0.051, "SE": 0.048, "DK": 0.027, "FI": 0.018,
        "BE": 0.015, "NO": 0.012, "IE": 0.010, "PL": 0.009, "AT": 0.009,
        "PT": 0.005, "LU": 0.005, "GR": 0.004,
    },
    "IE00BG47KH54": {
        "US": 0.472, "CN": 0.060, "FR": 0.060, "JP": 0.057, "DE": 0.055,
        "GB": 0.045, "CA": 0.040, "IT": 0.038, "ES": 0.026, "AU": 0.020,
    },
    "IE00B3F81R35": {
        "US": 0.212, "FR": 0.183, "DE": 0.127, "GB": 0.092, "ES": 0.055,
        "IT": 0.052, "NL": 0.046, "CH": 0.034, "SE": 0.027, "JP": 0.023,
        "DK": 0.022, "BE": 0.019, "AU": 0.016, "FI": 0.012, "AT": 0.012,
        "CA": 0.011, "LU": 0.009, "IE": 0.008, "NO": 0.007, "GR": 0.006,
        "PT": 0.005, "PL": 0.004, "CZ": 0.003, "NZ": 0.002,
    },
}


def vectors(dimension: str) -> dict[str, dict[str, float]]:
    """Return the seeded vectors for 'Sector' or 'Country'."""
    return SECTORS if dimension == "Sector" else COUNTRIES
