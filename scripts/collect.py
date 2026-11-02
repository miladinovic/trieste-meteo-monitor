#!/usr/bin/env python3
"""Incremental FVG API collector. API timestamps are retained as provided."""
import json, os, time, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'site' / 'data'
BASE = 'https://monitor.protezionecivile.fvg.it/api'
START = date(2023, 1, 1)
TODAY = datetime.now(timezone.utc).date()
BUDGET = int(os.getenv('FVG_BACKFILL_REQUESTS', '80'))
ALLOWED = {'T', 'U', 'P_1h', 'B', 'Vv', 'VvMax'}
# Seed IDs ensure useful data even if station discovery is temporarily unavailable.
SEED = [212, 191, 625, 502, 504]

def read(path, default):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError): return default

def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    tmp.replace(path)

def get(endpoint, params=None):
    url = BASE + endpoint
    if params: url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'TriesteMeteoMonitor/1.0'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=35) as r:
                result = json.load(r)
            if result.get('result') != 'OK': raise RuntimeError(str(result)[:300])
            return result
        except Exception:
            if attempt == 2: raise
            time.sleep(2 ** attempt)

def station_list():
    old = read(DATA / 'stations.json', [])
    by_id = {int(s['id']): s for s in old}
    try:
        payload = get('/stations', {'last': 10000, 'offset': 0})
        for s in payload.get('stations', []):
            if str(s.get('istat')) == '32006' and s.get('id') is not None:
                by_id[int(s['id'])] = s
    except Exception as exc:
        print('Station discovery unavailable:', exc)
    for sid in SEED:
        if sid not in by_id:
            try:
                p = get(f'/stations/{sid}')
                s = p.get('station')
                if isinstance(s, dict): by_id[sid] = s
            except Exception as exc: print('Station details unavailable', sid, exc)
    # Always retain known Trieste stations; additional ones must match ISTAT.
    out = sorted((s for s in by_id.values() if str(s.get('istat', '32006')) == '32006'), key=lambda s: (s.get('name') or '', s['id']))
    write(DATA / 'stations.json', out)
    return out

def sensor_list(stations):
    old = read(DATA / 'sensors.json', {})
    for station in stations:
        sid = str(station['id'])
        try:
            p = get(f'/stations/{sid}/sensors')
            sensors = p.get('sensors', [])
            if isinstance(sensors, list): old[sid] = sensors
        except Exception as exc: print('Sensor discovery unavailable', sid, exc)
    write(DATA / 'sensors.json', old)
    return old

def measure_page(sid, sensor, begin, finish, offset):
    return get(f'/stations/{sid}/sensors/{sensor}/measures', {
        'from': f'{begin} 00:00:00', 'to': f'{finish} 00:00:00',
        'last': 10000, 'offset': offset})

def fetch_window(sid, sensor, begin, finish):
    rows, offset = [], 0
    while True:
        payload = measure_page(sid, sensor, begin, finish, offset)
        page = payload.get('measures', [])
        if not isinstance(page, list): raise RuntimeError('Invalid measures list')
        rows.extend(page)
        offset += len(page)
        total = int(payload.get('total', offset))
        if offset >= total or not page: break
        if offset > 100000: raise RuntimeError('Unexpected pagination volume')
    return rows

def store(sid, sensor, rows):
    grouped = {}
    for r in rows:
        try:
            if int(r['station_id']) != sid or int(r['sensor_id']) != sensor: continue
            stamp = str(r['dt'])
            year = int(stamp[:4]); value = r.get('value')
            if value is None: continue
            value = float(value)
            if not (year >= 2023 and year <= TODAY.year): continue
            grouped.setdefault(year, {})[stamp] = value
        except (ValueError, KeyError, TypeError): continue
    for year, entries in grouped.items():
        path = DATA / 'history' / str(sid) / str(sensor) / f'{year}.json'
        old = read(path, {})
        old.update(entries)
        write(path, dict(sorted(old.items())))

def build_rain_comparison(sensors):
    """Precompute monthly rainfall totals, with coverage metadata, from hourly increments."""
    result = {'generated_at': datetime.now(timezone.utc).isoformat(), 'stations': {}}
    for sid, items in sensors.items():
        rain = next((x for x in items if x.get('code') == 'P_1h'), None)
        if not rain: continue
        months = {}
        for year in range(START.year, TODAY.year + 1):
            observations = read(DATA / 'history' / sid / str(rain['id']) / f'{year}.json', {})
            for stamp, value in observations.items():
                try:
                    key = stamp[:7]
                    bucket = months.setdefault(key, {'total': 0.0, 'observations': 0, 'first': stamp, 'last': stamp})
                    bucket['total'] += float(value)
                    bucket['observations'] += 1
                    bucket['first'] = min(bucket['first'], stamp)
                    bucket['last'] = max(bucket['last'], stamp)
                except (ValueError, TypeError): continue
        for bucket in months.values(): bucket['total'] = round(bucket['total'], 3)
        result['stations'][sid] = {'sensor_id': rain['id'], 'months': months}
    write(DATA / 'rainfall_monthly.json', result)

def main():
    DATA.mkdir(parents=True, exist_ok=True)
    stations = station_list()
    sensors = sensor_list(stations)
    state_path = DATA / 'collection_state.json'
    state = read(state_path, {'cursors': {}, 'last_updated': None})
    cursors = state.setdefault('cursors', {})
    pairs = [(int(s['id']), int(x['id'])) for s in stations for x in sensors.get(str(s['id']), [])
             if x.get('id') is not None and x.get('status') in ('O', None, 'N') and x.get('code') in ALLOWED]
    # Download recent observations FIRST so the website has data on the first run.
    # Rotate through all sensors; prioritize common weather sensors.
    primary = ALLOWED
    sensor_codes = {(int(st['id']), int(s['id'])): s.get('code', '')
                    for st in stations for s in sensors.get(str(st['id']), [])
                    if s.get('id') is not None}
    recent_pairs = sorted(pairs, key=lambda p: (sensor_codes.get(p) not in primary,
                                                p[0] != 504, p[0], p[1]))
    recent_budget = max(1, int(os.getenv('FVG_RECENT_REQUESTS', '35')))
    failures = []
    recent_calls = 0
    if recent_pairs:
        # First run begins with the important sensors; later runs rotate.
        cursor = int(state.get('recent_index', 0)) % len(recent_pairs)
        for i in range(min(recent_budget, len(recent_pairs))):
            sid, sensor = recent_pairs[(cursor + i) % len(recent_pairs)]
            try:
                rows = fetch_window(sid, sensor, TODAY - timedelta(days=3), TODAY + timedelta(days=1))
                store(sid, sensor, rows)
                recent_calls += 1
            except Exception as exc:
                failures.append(f'recent {sid}:{sensor}: {exc}')
                print('Recent error', sid, sensor, exc)
                if 'limit' in str(exc).lower() or '429' in str(exc): break
        state['recent_index'] = (cursor + max(1, recent_calls)) % len(recent_pairs)

    # Backfill from 2023 in 14-day windows; prioritize earliest incomplete periods.
    # No API calls are made by the browser itself.
    pairs.sort(key=lambda p: (cursors.get(f'{p[0]}:{p[1]}', str(START)),
                              sensor_codes.get(p) not in primary, p[0] != 504, p[0], p[1]))
    calls = 0
    for sid, sensor in pairs:
        if calls >= BUDGET: break
        key = f'{sid}:{sensor}'
        begin = date.fromisoformat(cursors.get(key, str(START)))
        if begin > TODAY: continue
        finish = min(begin + timedelta(days=14), TODAY + timedelta(days=1))
        try:
            rows = fetch_window(sid, sensor, begin, finish)
            store(sid, sensor, rows)
            cursors[key] = finish.isoformat()
            calls += 1
        except Exception as exc:
            failures.append(f'{key}: {exc}')
            print('Backfill error', key, exc)
            if 'limit' in str(exc).lower() or '429' in str(exc): break
    state['last_updated'] = datetime.now(timezone.utc).isoformat()
    state['last_attempts'] = calls
    state['recent_downloads'] = recent_calls
    state['sensor_count'] = len(pairs)
    state['recent_window_days'] = 2
    state['errors'] = failures[:12]
    write(state_path, state)
    build_rain_comparison(sensors)
    print('Backfill windows:', calls, 'Sensors:', len(pairs), 'Errors:', len(failures))

if __name__ == '__main__': main()
