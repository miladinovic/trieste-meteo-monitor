#!/usr/bin/env python3
"""Resumable local ARPA FVG historical downloader; standard library only.

Run: python scripts/backfill_local.py --check
     python scripts/backfill_local.py --delay 1 --window-days 7
     python scripts/backfill_local.py --check --strict
"""
import argparse
import calendar
import json
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import collect as core


def iso_day(value):
    return date.fromisoformat(value)


def pairs_for(stations, sensors):
    return sorted(((int(st['id']), int(s['id']), s['code'], st.get('name', str(st['id'])))
                   for st in stations for s in sensors.get(str(st['id']), [])
                   if s.get('code') in core.ALLOWED and s.get('id') is not None
                   and s.get('status') in ('O', 'N', None)), key=lambda x: (x[0], x[2], x[1]))


def audit(stations, sensors, state, end, strict=False):
    pairs = pairs_for(stations, sensors)
    print('\n=== HISTORICAL DATA SANITY CHECK ===')
    print('Stations:', len(stations), '| selected sensors:', len(pairs))
    if not pairs:
        print('ERROR: No selected sensors found. Run the downloader online first.')
        return False
    bad = 0
    empty = 0
    partial = 0
    completed = 0
    for sid, sensor, code, name in pairs:
        cursor = state.get('cursors', {}).get(f'{sid}:{sensor}', str(core.START))
        try: next_day = iso_day(cursor)
        except ValueError: next_day = core.START; bad += 1
        count = 0
        first = last = None
        invalid = 0
        for year in range(core.START.year, end.year + 1):
            path = core.DATA / 'history' / str(sid) / str(sensor) / f'{year}.json'
            if not path.exists(): continue
            try:
                obj = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(obj, dict): raise ValueError('Expected object')
                for stamp, val in obj.items():
                    try:
                        dt = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                        n = float(val)
                        if not (n == n and abs(n) != float('inf') and dt.year == year): raise ValueError()
                        if not (core.START <= dt.date() <= end): raise ValueError()
                        count += 1
                        first = min(first, stamp) if first else stamp
                        last = max(last, stamp) if last else stamp
                    except (ValueError, TypeError, OverflowError): invalid += 1
            except (ValueError, OSError, json.JSONDecodeError): invalid += 1
        if invalid: bad += invalid
        if not count: empty += 1
        if next_day <= end: partial += 1
        else: completed += 1
        print(f'{name[:22]:22} {code:7} #{sid}:{sensor:<5} records={count:<7} '
              f'first={str(first)[:10]:10} last={str(last)[:10]:10} '
              f'next={next_day} invalid={invalid}')
    print(f'Completed cursors: {completed}/{len(pairs)} | incomplete: {partial} | empty: {empty} | invalid records/files: {bad}')
    print('NOTE: Completed cursor means all requested date windows were queried successfully, NOT that every hour has a measurement.')
    rain = core.read(core.DATA / 'rainfall_monthly.json', {})
    print('Monthly rainfall cache:', 'present' if rain.get('stations') else 'missing or empty')
    good = not bad and not empty and not partial and bool(rain.get('stations'))
    if strict and not good: print('CHECK FAILED (strict mode).')
    else: print('CHECK FINISHED' + (' — incomplete data or gaps detected.' if not good else ' — cursors and files look consistent.'))
    return good


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true', help='Inspect local data without network access')
    parser.add_argument('--strict', action='store_true', help='Return failure status for incomplete data in check mode')
    parser.add_argument('--start', default=str(core.START), help='Start date, default 2023-01-01')
    parser.add_argument('--end', default=str(datetime.now(timezone.utc).date()), help='Last date inclusive')
    parser.add_argument('--window-days', type=int, default=7, help='Days per API request window (default 7)')
    parser.add_argument('--delay', type=float, default=1.0, help='Pause between successful windows (default 1 second)')
    parser.add_argument('--max-windows', type=int, default=0, help='Optional limit for a test run; 0 means unlimited')
    args = parser.parse_args()
    start, end = iso_day(args.start), iso_day(args.end)
    if start > end or args.window_days < 1 or args.delay < 0: parser.error('Invalid dates, window size or delay')
    state_path = core.DATA / 'collection_state.json'
    state = core.read(state_path, {'cursors': {}})
    if args.check:
        stations = core.read(core.DATA / 'stations.json', [])
        sensors = core.read(core.DATA / 'sensors.json', {})
        return 0 if audit(stations, sensors, state, end, args.strict) or not args.strict else 1
    print('Discovering stations and sensors from ARPA FVG…', flush=True)
    stations = core.station_list()
    sensors = core.sensor_list(stations)
    pairs = pairs_for(stations, sensors)
    if not pairs: print('No sensors found; stopping.'); return 1
    state.setdefault('cursors', {})
    failures = []
    windows = 0
    stop = False
    for index, (sid, sensor, code, name) in enumerate(pairs, 1):
        key = f'{sid}:{sensor}'
        try: begin = max(start, iso_day(state['cursors'].get(key, str(start))))
        except ValueError: begin = start
        print(f'[{index}/{len(pairs)}] {name} / {code} ({key}) from {begin}', flush=True)
        while begin <= end:
            finish = min(begin + timedelta(days=args.window_days), end + timedelta(days=1))
            try:
                rows = core.fetch_window(sid, sensor, begin, finish)
                core.store(sid, sensor, rows)
                # Checkpoint only after successful download and write.
                state['cursors'][key] = finish.isoformat()
                state['last_updated'] = datetime.now(timezone.utc).isoformat()
                core.write(state_path, state)
                windows += 1
                print(f'  {begin} → {finish} | fetched {len(rows)} | windows {windows}', flush=True)
                begin = finish
                if args.max_windows and windows >= args.max_windows: stop = True; break
                time.sleep(args.delay)
            except (KeyboardInterrupt, SystemExit):
                print('\nInterrupted. Saved progress can be resumed.', flush=True)
                core.build_rain_comparison(sensors)
                return 130
            except Exception as exc:
                print(f'  ERROR {key} {begin}: {exc} (cursor unchanged)', flush=True)
                failures.append(f'{key} {begin}: {exc}')
                # A failed window cannot be skipped without losing historical coverage.
                if '429' in str(exc) or 'limit' in str(exc).lower():
                    print('API rate limit suspected. Stop and retry later.', flush=True)
                    stop = True
                break
        if stop: break
    core.build_rain_comparison(sensors)
    print('\nWindows downloaded:', windows, '| failed sensors:', len(failures))
    audit(stations, sensors, core.read(state_path, {}), end)
    if failures: print('Failed windows (rerun to retry):', *failures[:20], sep='\n - ')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
