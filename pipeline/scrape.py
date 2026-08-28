"""Scrape Binance+Phemex a un snapshot fechado. Resumable dentro del snapshot."""
import json, os, time, urllib.request

BUA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
       'Content-Type': 'application/json', 'clienttype': 'web',
       'Origin': 'https://www.binance.com',
       'Referer': 'https://www.binance.com/en/copy-trading'}
PUA = {'User-Agent': BUA['User-Agent'], 'Accept': 'application/json',
       'Origin': 'https://phemex.com', 'Referer': 'https://phemex.com/'}
LIST_URL = 'https://www.binance.com/bapi/futures/v1/friendly/future/copy-trade/home-page/query-list'
HIST_URL = 'https://www.binance.com/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/position-history'
PH_REC = ('https://api.phemex.com/phemex-lb/public/data/v3/user/recommend'
          '?hideFullyCopied=false&keyword=&pageNum={}&pageSize=50&showChart=false'
          '&sortBy=PnlRate30d')
PH_POS = 'https://api.phemex.com/phemex-lb/public/data/position/closed/v2'


def _post(url, body, tries=3):
    # identico a scripts/scrape_binance.py::post
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=BUA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                return {'code': 'ERR'}
            time.sleep(2 * (i + 1))


def _get(url, tries=3):
    # identico a scripts/scrape_positions.py::get, headers PUA
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=PUA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                return {'error': 'fail'}
            time.sleep(2 * (i + 1))


def _done_ids(path, key):
    done = set()
    if os.path.exists(path):
        for line in open(path):
            try:
                done.add(json.loads(line)[key])
            except Exception:
                pass
    return done


def _fetch_portfolios(pages, post, time_range='90D', data_type='ROI'):
    """OJO: la API capea a 30/pagina aunque se pida 50 — cortar SOLO con
    pagina vacia, nunca con len(lst) < pageSize (cortaria en la pagina 1)."""
    rows = {}
    for p in range(1, pages + 1):
        body = {'pageNumber': p, 'pageSize': 50, 'timeRange': time_range,
                'dataType': data_type, 'favoriteOnly': False, 'hideFull': True,
                'nickname': '', 'order': 'DESC', 'userAsset': 0,
                'portfolioType': 'PUBLIC'}
        d = post(LIST_URL, body)
        if d.get('code') != '000000' or not d.get('data'):
            break
        lst = d['data'].get('list') or []
        for r in lst:
            rows[r['leadPortfolioId']] = r
        if not lst:
            break
        time.sleep(0.5)
    return list(rows.values())


def _fetch_history(pid, post):
    """Devuelve (rows, ok). ok=False si hubo ERR a mitad de paginacion —
    en ese caso el caller NO escribe el registro (el resume lo reintenta).
    NO copiar el bug de scripts/scrape_binance.py (ERR -> [] -> 'hecho')."""
    all_rows, page = [], 1
    while page <= 40:
        d = post(HIST_URL, {'portfolioId': pid, 'pageNumber': page, 'pageSize': 50})
        if d.get('code') == 'ERR':
            return all_rows, False
        if d.get('code') != '000000' or not d.get('data'):
            break
        rows = d['data'].get('list') or []
        all_rows += rows
        if len(rows) < 50:
            break
        page += 1
        time.sleep(0.4)
    return all_rows, True


def _scrape_binance(snap_dir, pages, post, extra_ids=()):
    portfolios = _fetch_portfolios(pages, post)
    json.dump(portfolios, open(os.path.join(snap_dir, 'binance_list.json'), 'w'),
              indent=1, ensure_ascii=False)
    print(f'lista binance: {len(portfolios)} portfolios', flush=True)
    raw = os.path.join(snap_dir, 'binance_raw.jsonl')
    done = _done_ids(raw, 'portfolioId')
    live_ids = {p['leadPortfolioId'] for p in portfolios}
    todo = [p for p in portfolios if p['leadPortfolioId'] not in done]
    # union historica: ids conocidos que ya no estan en la lista viva
    todo += [{'leadPortfolioId': pid} for pid in extra_ids
             if pid not in live_ids and pid not in done]
    print(f'binance a scrapear: {len(todo)} | ya hechos: {len(done)}', flush=True)
    out = open(raw, 'a')
    fetched = 0
    for p in todo:
        pid = p['leadPortfolioId']
        rows, ok = _fetch_history(pid, post)
        if not ok:            # fallo de red != trader hecho: no escribir
            print(f'  ERR historial {pid} — se reintenta en el proximo resume',
                  flush=True)
            time.sleep(0.5)
            continue
        rec = {'portfolioId': pid, 'nick': p.get('nickname'), 'roi': p.get('roi'),
               'pnl': p.get('pnl'), 'aum': p.get('aum'), 'winRate': p.get('winRate'),
               'mdd': p.get('mdd'), 'n_pos': len(rows), 'positions': rows}
        out.write(json.dumps(rec, ensure_ascii=False) + '\n')
        out.flush()
        fetched += 1
        if fetched % 25 == 0:
            print(f'  {fetched} portfolios', flush=True)
        time.sleep(0.5)
    out.close()
    return fetched


def _fetch_trader_list(pages, get):
    rows = {}
    for p in range(1, pages + 1):
        d = get(PH_REC.format(p))
        if d.get('code') != 0 or not d.get('data'):
            break
        lst = d['data'].get('rows') or []
        for r in lst:
            rows[r['userId']] = r
        if not lst:
            break
        time.sleep(0.4)
    return [{'userId': r['userId'], 'nick': r['nickName'], 'roi30': r['pnlRate30d'],
             'pnl30': r['pnl30d'], 'wr30': r['tradeWinRate30d'], 'aum': r['aum'],
             'followers': r['followerCount'], 'mdd30': r['mdd30d'],
             'showPosition': r['showPosition']} for r in rows.values()]


def _fetch_closed(uid, get):
    """Devuelve (rows, ok); ok=False si la red fallo (no marcar hecho)."""
    all_rows, page, empty = [], 1, 0
    while page <= 30 and empty < 2:
        d = get(f"{PH_POS}?pageNum={page}&pageSize=100&userId={uid}")
        if d.get('error'):
            return all_rows, False
        if d.get('code') != 0 or not d.get('data'):
            empty += 1
            page += 1
            continue
        rows = d['data'].get('rows') or []
        all_rows += rows
        if len(rows) < 100:
            break
        page += 1
        time.sleep(0.4)
    return all_rows, True


def _scrape_phemex(snap_dir, pages, get):
    traders = _fetch_trader_list(pages, get)
    json.dump(traders, open(os.path.join(snap_dir, 'phemex_list.json'), 'w'),
              indent=1, ensure_ascii=False)
    print(f'lista phemex: {len(traders)} traders', flush=True)
    raw = os.path.join(snap_dir, 'phemex_raw.jsonl')
    done = _done_ids(raw, 'userId')
    todo = [t for t in traders if t['showPosition'] and t['userId'] not in done]
    print(f'phemex a scrapear: {len(todo)} | ya hechos: {len(done)}', flush=True)
    out = open(raw, 'a')
    fetched = 0
    for t in todo:
        rows, ok = _fetch_closed(t['userId'], get)
        if not ok:            # fallo de red != trader hecho
            print(f"  ERR posiciones {t['userId']} — se reintenta en el resume",
                  flush=True)
            time.sleep(0.4)
            continue
        rec = {'userId': t['userId'], 'nick': t['nick'], 'n_pos': len(rows),
               'positions': rows}
        out.write(json.dumps(rec, ensure_ascii=False) + '\n')
        out.flush()
        fetched += 1
        if fetched % 25 == 0:
            print(f'  {fetched} traders nuevos', flush=True)
        time.sleep(0.4)
    out.close()
    return fetched


def run(snap_dir, exchanges=('binance', 'phemex'), pages_binance=20,
        pages_phemex=7, extra_ids_binance=(), http_post=None, http_get=None):
    os.makedirs(str(snap_dir), exist_ok=True)
    post, get = http_post or _post, http_get or _get
    out = {}
    if 'binance' in exchanges:
        out['binance'] = _scrape_binance(str(snap_dir), pages_binance, post,
                                         extra_ids_binance)
    if 'phemex' in exchanges:
        out['phemex'] = _scrape_phemex(str(snap_dir), pages_phemex, get)
    return out
