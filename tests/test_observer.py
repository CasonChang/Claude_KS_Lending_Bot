"""學習觀察者的差異偵測（diff_events 純函式）測試。"""
from lendbot.bfx_client import Credit, Offer
from lendbot.observer import diff_events

NOW = 1_700_000_000_000


def offer(oid, amount=1000.0, rate=0.0003, period=2, created=NOW - 3_600_000):
    return Offer(id=oid, symbol="fUSD", mts_created=created,
                 amount=amount, rate=rate, period=period)


def credit(cid, amount=1000.0, rate=0.0003, period=2, opened=NOW - 3_600_000):
    return Credit(id=cid, symbol="fUSD", amount=amount, rate=rate,
                  period=period, mts_opening=opened)


def by_event(events, name):
    return [e for e in events if e["event"] == name]


def test_no_change_no_events():
    offers = {1: offer(1)}
    credits = {10: credit(10)}
    assert diff_events(offers, offers, credits, credits, NOW) == []


def test_new_offer():
    events = diff_events({}, {1: offer(1, amount=500, rate=0.0004, period=30)},
                         {}, {}, NOW)
    assert len(events) == 1
    e = events[0]
    assert e["event"] == "offer_new"
    assert e["offer_id"] == 1
    assert e["amount"] == 500
    assert e["period"] == 30
    assert e["apy"] > 0


def test_offer_gone_without_credit_is_cancel():
    events = diff_events({1: offer(1)}, {}, {}, {}, NOW)
    assert [e["event"] for e in events] == ["offer_canceled"]


def test_offer_gone_with_matching_credit_is_fill():
    o = offer(1, amount=1000, rate=0.0004, period=30)
    c = credit(99, amount=1000, rate=0.0004, period=30, opened=NOW)
    events = diff_events({1: o}, {}, {}, {99: c}, NOW)
    fills = by_event(events, "offer_filled")
    assert len(fills) == 1
    assert fills[0]["detail"] == {"credit_id": 99}
    assert not by_event(events, "offer_canceled")
    # 同一筆成交只記一則：已由 offer_filled 記到，不再重複記 credit_new
    assert not by_event(events, "credit_new")


def test_new_credit_without_seen_offer_is_fast_fill():
    # 掛單在兩次輪詢間掛出又秒成交、沒捕捉到 offer → 只會有 credit_new（標記 fast_fill）
    c = credit(99, amount=500, rate=0.0004, period=2, opened=NOW)
    events = diff_events({}, {}, {}, {99: c}, NOW)
    news = by_event(events, "credit_new")
    assert len(news) == 1
    assert news[0]["detail"] == {"fast_fill": True}
    assert not by_event(events, "offer_filled")


def test_offer_gone_with_different_rate_credit_is_cancel():
    o = offer(1, rate=0.0004, period=30)
    c = credit(99, rate=0.0005, period=30, opened=NOW)  # 利率不同 → 不是這張成交
    events = diff_events({1: o}, {}, {}, {99: c}, NOW)
    assert len(by_event(events, "offer_canceled")) == 1
    assert not by_event(events, "offer_filled")


def test_partial_fill():
    events = diff_events({1: offer(1, amount=1000)}, {1: offer(1, amount=400)},
                         {}, {}, NOW)
    parts = by_event(events, "offer_partial_fill")
    assert len(parts) == 1
    assert parts[0]["amount"] == 600
    assert parts[0]["detail"] == {"from": 1000, "to": 400}


def test_credit_closed_early_vs_matured():
    early = credit(1, period=30, opened=NOW - 5 * 86_400_000)    # 30 天期只放 5 天
    matured = credit(2, period=2, opened=NOW - 2 * 86_400_000)   # 2 天期放滿
    events = diff_events({}, {}, {1: early, 2: matured}, {}, NOW)
    closed = {e["offer_id"]: e for e in by_event(events, "credit_closed")}
    assert closed[1]["detail"]["matured"] is False
    assert closed[1]["detail"]["held_days"] == 5.0
    assert closed[2]["detail"]["matured"] is True


def test_two_offers_one_credit_matches_only_one():
    o1 = offer(1, amount=1000, rate=0.0004, period=30)
    o2 = offer(2, amount=1000, rate=0.0004, period=30)
    c = credit(99, amount=1000, rate=0.0004, period=30, opened=NOW)
    events = diff_events({1: o1, 2: o2}, {}, {}, {99: c}, NOW)
    assert len(by_event(events, "offer_filled")) == 1
    assert len(by_event(events, "offer_canceled")) == 1
