from pipeline import rank

EX, D = "binance", "2026-09-01"


def _tm(con, tid, t=4.0, alpha=0.015, payoff=1.2, tb=0.5, n=400, flags='[]'):
    con.execute(
        "INSERT INTO trader_metrics (snapshot_date,exchange,trader_id,nick,n,n_alpha,"
        "alpha,t_stat,payoff,trend_bonus,flags) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (D, EX, tid, tid, n, n, alpha, t, payoff, tb, flags))
    con.commit()


def test_score_formula_and_warning_penalty(con):
    _tm(con, "A")                                   # limpio
    _tm(con, "B", flags='["alpha_decay"]')          # 1 warning
    r = rank.run(con, D, EX)
    sa = next(t for t in r["traders"] if t["nick"] == "A")["score"]
    sb = next(t for t in r["traders"] if t["nick"] == "B")["score"]
    expected = 0.40*4.0 + 0.25*1.5 + 0.20*1.2 + 0.15*0.5
    assert abs(sa - expected) < 1e-9
    assert abs(sb - expected*0.9) < 1e-9


def test_disqualified_excluded_and_cap5(con):
    for i in range(7):
        _tm(con, f"t{i}", t=5.0 - i*0.2)
    _tm(con, "bad", t=9.9, flags='["loss_hider"]')
    r = rank.run(con, D, EX)
    nicks = [t["nick"] for t in r["traders"]]
    assert "bad" not in nicks and len(nicks) == 5
    assert nicks[0] == "t0"                          # mayor score primero


def test_tiers_and_weights(con):
    _tm(con, "vet", n=400)                           # A (n>300, 0 warnings)
    _tm(con, "rookie", n=100, flags='["alpha_decay"]')  # B
    r = rank.run(con, D, EX)
    by = {t["nick"]: t for t in r["traders"]}
    assert by["vet"]["tier"] == "A" and by["rookie"]["tier"] == "B"
    assert abs(sum(t["weight"] for t in r["traders"]) - 1.0) < 1e-9
    assert by["rookie"]["weight"] <= 0.10 + 1e-9
    assert all(abs(t["weight"] * 20 - round(t["weight"] * 20)) < 1e-6
               for t in r["traders"])                # multiplos de 0.05


def test_material_on_tier_a_change(con):
    _tm(con, "vet", n=400)
    diff = {"material": False, "added_a": [], "removed_a": [], "weight_moves": []}
    prev = {"traders": [{"portfolio_id": "otro", "nick": "otro",
                         "tier": "A", "weight": 0.5}]}
    rank.run(con, D, EX, diff=diff, prev_roster=prev)
    assert "vet" in diff["added_a"] and "otro" in diff["removed_a"]
    # la salida del titular tambien aparece como weight_move prev->0
    assert any(m["nick"] == "otro" and m["now"] == 0.0
               for m in diff["weight_moves"])
    assert diff["material"] is True


def test_weights_all_B_respects_cap_and_leaves_unallocated(con):
    # corrida #1 tipica: nadie califica a tier A (todos con warning)
    for i in range(5):
        _tm(con, f"b{i}", t=4.0 - i * 0.1, n=100, flags='["alpha_decay"]')
    r = rank.run(con, D, EX)
    assert all(t["tier"] == "B" for t in r["traders"])
    assert all(t["weight"] <= 0.10 + 1e-9 for t in r["traders"])   # cap SIEMPRE
    assert abs(sum(t["weight"] for t in r["traders"]) - 0.50) < 1e-9
    assert abs(r["unallocated"] - 0.50) < 1e-9   # remanente declarado, no volcado


def test_insufficient_only_goes_to_W_not_X(con):
    _tm(con, "novato", n=30, flags='["insufficient"]')
    _tm(con, "fraude", n=100, flags='["loss_hider"]')
    rank.run(con, D, EX)
    tiers = {r["trader_id"]: r["tier"] for r in con.execute(
        "SELECT trader_id, tier FROM trader_metrics WHERE snapshot_date=?", (D,))}
    assert tiers["novato"] == "W" and tiers["fraude"] == "X"
