import importlib.util, json, pathlib, shutil

# pipeline.py (file) collides with pipeline/ (package): load the CLI by path
_spec = importlib.util.spec_from_file_location(
    "cli", pathlib.Path(__file__).parent.parent / "pipeline.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


def _setup_project(tmp_path, snap_fixture, date="2026-09-01"):
    root = tmp_path / "proj"
    (root / "data" / "snapshots" / date).mkdir(parents=True)
    for f in snap_fixture.iterdir():
        shutil.copy(f, root / "data" / "snapshots" / date / f.name)
    return root


def test_analyze_end_to_end_and_publish_gate(tmp_path, snap_dir):
    root = _setup_project(tmp_path, snap_dir)
    rc = cli.main(["analyze", "--date", "2026-09-01"], project_root=str(root))
    assert rc == 0
    run_dir = root / "analysis" / "runs" / "2026-09-01"
    roster = json.loads((run_dir / "roster.json").read_text())
    diff = json.loads((run_dir / "diff.json").read_text())
    assert roster["snapshot"] == "2026-09-01"
    assert diff["material"] is True            # first run
    assert (run_dir / "TOP_2026-09.md").exists()
    # analyze does NOT publish the latest — that is publish, after the gate
    assert not (root / "analysis" / "roster.json").exists()
    rc = cli.main(["publish", "--date", "2026-09-01"], project_root=str(root))
    assert rc == 0
    assert (root / "analysis" / "roster.json").exists()


def test_analyze_aborts_on_missing_snapshot_dir(tmp_path, snap_dir):
    root = _setup_project(tmp_path, snap_dir)
    # typo in --date: must not produce a roster (least of all an empty one)
    rc = cli.main(["analyze", "--date", "2026-12-31"], project_root=str(root))
    assert rc == 2
    assert not (root / "analysis" / "runs" / "2026-12-31").exists()


def test_analyze_validation_blocks_partial_data(tmp_path, snap_dir):
    root = _setup_project(tmp_path, snap_dir, "2026-09-01")
    cli.main(["analyze", "--date", "2026-09-01"], project_root=str(root))
    # second snapshot with 5x the positions -> outside +-50%
    d2 = root / "data" / "snapshots" / "2026-10-01"
    d2.mkdir()
    lines = (snap_dir / "binance_raw.jsonl").read_text()
    rec = json.loads(lines)
    rec["positions"] = rec["positions"] * 5
    (d2 / "binance_raw.jsonl").write_text(json.dumps(rec) + "\n")
    rc = cli.main(["analyze", "--date", "2026-10-01"], project_root=str(root))
    assert rc == 2
    # the DB was NOT poisoned: the rejected snapshot is absent from `snapshots`
    from pipeline import db as dbmod
    con = dbmod.connect(root / "data" / "copytrade.sqlite")
    assert con.execute("SELECT COUNT(*) FROM snapshots "
                       "WHERE snapshot_date='2026-10-01'").fetchone()[0] == 0
    con.close()
    rc = cli.main(["analyze", "--date", "2026-10-01", "--force"],
                  project_root=str(root))
    assert rc == 0


# --- the `detail` pass (2026-09-23) -----------------------------------------

def test_detail_fetches_only_the_ranked_candidates(tmp_path, snap_dir, monkeypatch):
    """`lead-portfolio/detail` is one request per portfolio at >=1.5s, so it runs
    over the traders a roster could actually contain — everything that survives
    every OTHER disqualifier — and not over the whole universe."""
    root = _setup_project(tmp_path, snap_dir)
    cli.main(["analyze", "--date", "2026-09-01"], project_root=str(root))
    from pipeline import db as dbmod
    con = dbmod.connect(root / "data" / "copytrade.sqlite")
    for tid, flags in (("OK", "[]"), ("DISQ", '["loss_hider"]')):
        con.execute("INSERT INTO trader_metrics (snapshot_date,exchange,trader_id,"
                    "nick,n,score,flags) VALUES ('2026-09-01','binance',?,?,"
                    "100,5.0,?)", (tid, tid, flags))
    con.commit()
    con.close()
    seen = []
    monkeypatch.setattr(cli.scrape_mod, "run_detail",
                        lambda snap, ids, **kw: seen.append(list(ids)) or len(ids))
    rc = cli.main(["detail", "--date", "2026-09-01"], project_root=str(root))
    assert rc == 0
    # P1 is out too: one position, so `insufficient`
    assert seen == [["OK"]]


def test_detail_all_covers_the_whole_snapshot(tmp_path, snap_dir, monkeypatch):
    root = _setup_project(tmp_path, snap_dir)
    cli.main(["analyze", "--date", "2026-09-01"], project_root=str(root))
    from pipeline import db as dbmod
    con = dbmod.connect(root / "data" / "copytrade.sqlite")
    con.execute("INSERT INTO trader_snapshot (snapshot_date,exchange,trader_id,"
                "nick) VALUES ('2026-09-01','binance','OTHER','other')")
    con.commit()
    con.close()
    seen = []
    monkeypatch.setattr(cli.scrape_mod, "run_detail",
                        lambda snap, ids, **kw: seen.append(list(ids)) or len(ids))
    assert cli.main(["detail", "--date", "2026-09-01", "--all"],
                    project_root=str(root)) == 0
    assert set(seen[0]) == {"P1", "OTHER"}


def test_detail_keeps_measuring_a_trader_the_copier_gate_removed(tmp_path,
                                                                 snap_dir,
                                                                 monkeypatch):
    """`copiers_losing` is the one disqualifier that would switch itself off: skip
    the trader's next `detail` call and its copier record goes back to NULL, the
    gate falls silent and the lead returns to the roster."""
    root = _setup_project(tmp_path, snap_dir)
    cli.main(["analyze", "--date", "2026-09-01"], project_root=str(root))
    from pipeline import db as dbmod
    con = dbmod.connect(root / "data" / "copytrade.sqlite")
    con.execute("INSERT INTO trader_metrics (snapshot_date,exchange,trader_id,"
                "nick,n,score,flags) VALUES ('2026-09-01','binance','GATED',"
                "'gated',100,5.0,'[\"copiers_losing\"]')")
    con.commit()
    con.close()
    seen = []
    monkeypatch.setattr(cli.scrape_mod, "run_detail",
                        lambda snap, ids, **kw: seen.append(list(ids)) or len(ids))
    assert cli.main(["detail", "--date", "2026-09-01"],
                    project_root=str(root)) == 0
    assert seen == [["GATED"]]
