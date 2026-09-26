import pytest

from openview.trades import parse_trade_csv


def test_canonical_and_aliases():
    canonical = """symbol,side,entry_time,entry_price,exit_time,exit_price,quantity,pnl,tag
RELIANCE,long,2024-01-15T09:45:00+05:30,2488.50,2024-01-15T11:15:00+05:30,2506.20,100,1770,orb
"""
    parsed = parse_trade_csv(canonical)
    trade = parsed["trades"][0]
    assert trade["symbol"] == "RELIANCE"
    assert trade["side"] == "long"
    assert trade["entry_price"] == 2488.5
    assert trade["pnl"] == 1770
    assert trade["exit_time"] > trade["entry_time"]

    legacy = """Symbol,Type,Entry Time,Exit Time,Entry Price,Exit Price,PnL,Reason
reliance,Long,2024-01-16 10:05:00,2024-01-16 13:20:00,2510,2494.75,762.5,vwap
TCS,sell,2024-02-01 09:30:00,,4000,,
"""
    parsed = parse_trade_csv(legacy)
    assert parsed["errors"] == []
    assert parsed["trades"][0]["symbol"] == "RELIANCE"
    assert parsed["trades"][0]["side"] == "long"
    assert parsed["trades"][0]["tag"] == "vwap"
    # Naive clock times are Asia/Kolkata, so 10:05 IST is 04:35 UTC.
    assert parsed["trades"][0]["entry_time"] == 1705379700
    assert parsed["trades"][1]["side"] == "short"
    assert parsed["trades"][1]["exit_time"] is None
    assert parsed["trades"][1]["symbol"] == "TCS"


def test_default_symbol_and_row_errors():
    text = """side,entry_time,entry_price
buy,2024-01-03T09:20:00+05:30,10
hold,not-a-time,12
"""
    parsed = parse_trade_csv(text, default_symbol="infy")
    assert parsed["trades"][0]["symbol"] == "INFY"
    assert parsed["trades"][0]["side"] == "long"
    assert len(parsed["errors"]) == 1
    assert "row 3" in parsed["errors"][0]


def test_missing_header_is_rejected():
    with pytest.raises(ValueError, match="Missing column"):
        parse_trade_csv("foo,bar\n1,2\n")
