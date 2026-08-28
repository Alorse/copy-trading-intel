import importlib.util, json, pathlib, shutil

# pipeline.py (archivo) colisiona con pipeline/ (paquete): cargar el CLI por path
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
    assert diff["material"] is True            # primera corrida
    assert (run_dir / "TOP_2026-09.md").exists()
    # analyze NO publica el latest — eso es publish, tras el gate
    assert not (root / "analysis" / "roster.json").exists()
    rc = cli.main(["publish", "--date", "2026-09-01"], project_root=str(root))
    assert rc == 0
    assert (root / "analysis" / "roster.json").exists()


def test_analyze_aborts_on_missing_snapshot_dir(tmp_path, snap_dir):
    root = _setup_project(tmp_path, snap_dir)
    # typo en --date: no debe producir un roster (menos aun uno vacio)
    rc = cli.main(["analyze", "--date", "2026-12-31"], project_root=str(root))
    assert rc == 2
    assert not (root / "analysis" / "runs" / "2026-12-31").exists()


def test_analyze_validation_blocks_partial_data(tmp_path, snap_dir):
    root = _setup_project(tmp_path, snap_dir, "2026-09-01")
    cli.main(["analyze", "--date", "2026-09-01"], project_root=str(root))
    # segundo snapshot con 5x las posiciones -> fuera de +-50%
    d2 = root / "data" / "snapshots" / "2026-10-01"
    d2.mkdir()
    lines = (snap_dir / "binance_raw.jsonl").read_text()
    rec = json.loads(lines)
    rec["positions"] = rec["positions"] * 5
    (d2 / "binance_raw.jsonl").write_text(json.dumps(rec) + "\n")
    rc = cli.main(["analyze", "--date", "2026-10-01"], project_root=str(root))
    assert rc == 2
    # la DB NO quedo envenenada: el snapshot rechazado no existe en `snapshots`
    from pipeline import db as dbmod
    con = dbmod.connect(root / "data" / "copytrade.sqlite")
    assert con.execute("SELECT COUNT(*) FROM snapshots "
                       "WHERE snapshot_date='2026-10-01'").fetchone()[0] == 0
    con.close()
    rc = cli.main(["analyze", "--date", "2026-10-01", "--force"],
                  project_root=str(root))
    assert rc == 0
