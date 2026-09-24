from conftest import insert_trader_snapshot
from pipeline import rank

EX, D = "binance", "2026-09-01"


def _tm(con, tid, t=4.0, alpha=0.015, payoff=1.2, tb=0.5, n=400, flags='[]'):
    con.execute(
        "INSERT INTO trader_metrics (snapshot_date,exchange,trader_id,nick,n,n_alpha,"
        "alpha,t_stat,payoff,trend_bonus,flags) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (D, EX, tid, tid, n, n, alpha, t, payoff, tb, flags))
    con.commit()


def test_score_formula_and_warning_penalty(con):
    _tm(con, "A")                                   # clean
    _tm(con, "B", flags='["alpha_decay"]')          # 1 warning
    r = rank.run(con, D, EX)
    sa = next(t for t in r["traders"] if t["nick"] == "A")["score"]
    sb = next(t for t in r["traders"] if t["nick"] == "B")["score"]
    expected = 0.40*4.0 + 0.25*1.5 + 0.20*1.2 + 0.15*0.5
    assert abs(sa - expected) < 1e-9
    assert abs(sb - expected*0.9) < 1e-9


def test_metrics_block_exposes_n_alpha(con):
    # the t-stat rests on n_alpha (positions with computable alpha), which can
    # be far smaller than n — the roster must disclose it
    con.execute(
        "INSERT INTO trader_metrics (snapshot_date,exchange,trader_id,nick,n,n_alpha,"
        "alpha,t_stat,payoff,trend_bonus,flags) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (D, EX, "gap", "gap", 400, 120, 0.015, 4.0, 1.2, 0.5, '[]'))
    con.commit()
    m = rank.run(con, D, EX)["traders"][0]["metrics"]
    assert m["n"] == 400 and m["n_alpha"] == 120


def test_metrics_block_exposes_roi(con):
    # the roster's own headline ROI: without it the report forces you to look at
    # the excluded traders' ROI and not the picked ones'
    _tm(con, "vet")
    insert_trader_snapshot(con, D, EX, "vet", roi=412.5, mdd=20.0)
    m = rank.run(con, D, EX)["traders"][0]["metrics"]
    assert m["roi"] == 412.5


def test_disqualified_excluded_and_cap5(con):
    for i in range(7):
        _tm(con, f"t{i}", t=5.0 - i*0.2)
    _tm(con, "bad", t=9.9, flags='["loss_hider"]')
    r = rank.run(con, D, EX)
    nicks = [t["nick"] for t in r["traders"]]
    assert "bad" not in nicks and len(nicks) == 5
    assert nicks[0] == "t0"                          # highest score first


def test_tiers_and_weights(con):
    _tm(con, "vet", n=400)                           # A (n>300, 0 warnings)
    _tm(con, "rookie", n=100, flags='["alpha_decay"]')  # B
    r = rank.run(con, D, EX)
    by = {t["nick"]: t for t in r["traders"]}
    assert by["vet"]["tier"] == "A" and by["rookie"]["tier"] == "B"
    # allocated + unallocated == 1.0: since the per-trader cap, the book is no
    # longer fully allocated just because tier A exists (it was vet 0.90 +
    # rookie 0.10 before the cap)
    assert abs(sum(t["weight"] for t in r["traders"])
               + r["unallocated"] - 1.0) < 1e-9
    assert by["rookie"]["weight"] <= 0.10 + 1e-9
    assert all(abs(t["weight"] * 20 - round(t["weight"] * 20)) < 1e-6
               for t in r["traders"])                # multiples of 0.05


def test_material_on_tier_a_change(con):
    _tm(con, "vet", n=400)
    diff = {"material": False, "added_a": [], "removed_a": [], "weight_moves": []}
    prev = {"traders": [{"portfolio_id": "otro", "nick": "otro",
                         "tier": "A", "weight": 0.5}]}
    rank.run(con, D, EX, diff=diff, prev_roster=prev)
    assert "vet" in diff["added_a"] and "otro" in diff["removed_a"]
    # the incumbent's exit also shows up as a weight_move prev->0
    assert any(m["nick"] == "otro" and m["now"] == 0.0
               for m in diff["weight_moves"])
    assert diff["material"] is True


def test_weights_all_B_respects_cap_and_leaves_unallocated(con):
    # typical run #1: nobody qualifies for tier A (everyone has a warning)
    for i in range(5):
        _tm(con, f"b{i}", t=4.0 - i * 0.1, n=100, flags='["alpha_decay"]')
    r = rank.run(con, D, EX)
    assert all(t["tier"] == "B" for t in r["traders"])
    assert all(t["weight"] <= 0.10 + 1e-9 for t in r["traders"])   # cap ALWAYS
    assert abs(sum(t["weight"] for t in r["traders"]) - 0.50) < 1e-9
    assert abs(r["unallocated"] - 0.50) < 1e-9   # remainder declared, not dumped


def test_insufficient_only_goes_to_W_not_X(con):
    _tm(con, "newbie_ins", n=30, flags='["insufficient"]')
    _tm(con, "fraud", n=100, flags='["loss_hider"]')
    rank.run(con, D, EX)
    tiers = {r["trader_id"]: r["tier"] for r in con.execute(
        "SELECT trader_id, tier FROM trader_metrics WHERE snapshot_date=?", (D,))}
    assert tiers["newbie_ins"] == "W" and tiers["fraud"] == "X"


def test_unscreenable_traders_go_to_watchlist_not_excluded(con):
    """W = newcomers and traders we could not screen; X = defects.

    `insufficient` already had this carve-out, written as an exact-set match so
    it silently stopped carving the moment a second not-a-defect flag existed.
    `no_listing_data` is that second flag: it says the listing row was missing,
    not that the trader did anything wrong, and the report publishes tier X
    beside `loss_hider` and `roi_artifact`.
    """
    _tm(con, "clean")                                        # fills the roster
    _tm(con, "newcomer", flags='["insufficient"]')
    _tm(con, "unscreenable", flags='["no_listing_data"]')
    _tm(con, "both", flags='["insufficient", "no_listing_data"]')
    _tm(con, "fraud", flags='["loss_hider"]')
    _tm(con, "mixed", flags='["no_listing_data", "loss_hider"]')
    rank.run(con, D, EX)
    tiers = {r["trader_id"]: r["tier"] for r in con.execute(
        "SELECT trader_id, tier FROM trader_metrics WHERE snapshot_date=?", (D,))}
    assert tiers["newcomer"] == "W"
    assert tiers["unscreenable"] == "W"
    assert tiers["both"] == "W"
    assert tiers["fraud"] == "X"
    assert tiers["mixed"] == "X"          # a real defect still outranks the caveat
    # and neither reaches the roster either way
    assert {t["nick"] for t in rank.run(con, D, EX)["traders"]} == {"clean"}


# --- the per-trader weight cap (2026-09-23) ---------------------------------
# The A pool is 70% of the book (100% with no B), split by score, so a single
# tier-A trader took ALL of it: on 2026-09-23 汤普猫 was handed 70% on 84 trades,
# t=2.58 and a $2,001 lead account. One lead cannot be the book, whatever it
# scores — 牛熊摆渡人 closed 14 positions for -15,295 USDT in one second.

def test_no_trader_exceeds_the_cap(con):
    _tm(con, "solo", n=400)                       # the only survivor, tier A
    r = rank.run(con, D, EX)
    assert r["traders"][0]["weight"] == rank.MAX_WEIGHT
    assert rank.MAX_WEIGHT <= 0.20                # the 2026-08 hand ranking's max


def test_cap_excess_stays_unallocated_instead_of_moving_to_others(con):
    _tm(con, "vet", n=400)                             # A
    _tm(con, "rookie", n=100, flags='["alpha_decay"]')  # B
    r = rank.run(con, D, EX)
    by = {t["nick"]: t["weight"] for t in r["traders"]}
    assert by["vet"] == rank.MAX_WEIGHT                # not 0.70, not 0.90
    assert by["rookie"] == 0.10                        # B's own cap is stricter
    assert abs(r["unallocated"] - (1.0 - rank.MAX_WEIGHT - 0.10)) < 1e-9


def test_cap_excess_within_the_a_pool_goes_to_the_other_a_traders(con):
    # the excess is not dumped on the book, but inside a tier it still follows
    # score — up to each trader's own cap
    _tm(con, "big", t=9.0, n=400)
    _tm(con, "small", t=3.0, n=400)
    r = rank.run(con, D, EX)
    by = {t["nick"]: t["weight"] for t in r["traders"]}
    assert by["big"] == rank.MAX_WEIGHT
    assert 0 < by["small"] <= rank.MAX_WEIGHT


def test_the_2026_09_23_concentration_is_capped(con):
    # the real shape of that run: one clean tier-A trader and four tier-B ones
    _tm(con, "tangpu", t=2.58, alpha=0.029, payoff=1.41, tb=0.0, n=84)
    con.execute("INSERT INTO trader_metrics (snapshot_date,exchange,trader_id,"
                "nick,n) VALUES ('2026-08-28',?,'tangpu','tangpu',80)", (EX,))
    con.commit()                                   # seen in 2 snapshots -> A
    for i, nick in enumerate(("suoha", "cooma", "heipao", "zhsheng")):
        _tm(con, nick, t=4.0 - i * 0.3, n=300, flags='["alpha_decay"]')
    r = rank.run(con, D, EX)
    by = {t["nick"]: t["weight"] for t in r["traders"]}
    assert by["tangpu"] == rank.MAX_WEIGHT             # was 0.70
    assert max(by.values()) <= rank.MAX_WEIGHT
