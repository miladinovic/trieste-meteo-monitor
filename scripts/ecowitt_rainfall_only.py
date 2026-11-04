#!/usr/bin/env python3
"""Backfill Ecowitt DAILY rainfall totals into P_daily; never touch P_1h.

Usage: python3 scripts/ecowitt_rainfall_only.py --start 2023-01-01 --end 2026-11-03
       python3 scripts/ecowitt_rainfall_only.py --check

The highest observed 'daily' counter for a station-local calendar day is saved.
Sparse days are flagged in P_daily_quality; a single reading does NOT prove
that the day's final rainfall was captured. Verify against Ecowitt exports.
"""
import argparse
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ecowitt_local import query, points, OUT

TZ = ZoneInfo(os.getenv('ECOWITT_TIMEZONE', 'Europe/Rome'))


def load(path):
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'Unexpected format: {path}')
    return value


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(dict(sorted(obj.items())), separators=(',', ':')), encoding='utf-8')
    tmp.replace(path)


def daily_observations(data):
    grouped = {}
    for stamp, value in points(data, 'rainfall', 'daily').items():
        if value < 0:
            continue
        utc = datetime.fromisoformat(stamp.replace(' ', 'T')).replace(tzinfo=timezone.utc)
        local = utc.astimezone(TZ)
        key = local.date().isoformat()
        group = grouped.setdefault(key, [])
        group.append((local, value))
    return grouped


def merge_day(day, samples):
    year = day[:4]
    values_path = OUT / 'P_daily' / f'{year}.json'
    quality_path = OUT / 'P_daily_quality' / f'{year}.json'
    values = load(values_path)
    quality = load(quality_path)
    # Counter is cumulative since local midnight. Maximum is robust against
    # sparse sampling but may be an underestimate if the last reading is early.
    total = round(max(v for _, v in samples), 3)
    last_local = max(t for t, _ in samples)
    new_quality = {'observations': len(samples), 'last_local': last_local.isoformat(timespec='seconds'),
                   'complete': False, 'method': 'max_daily_counter',
                   'warning': 'Not independently verified as final daily total'}
    # Replace a previously sampled value only if new maximum is higher;
    # never silently replace with a smaller incomplete reading.
    if day not in values or total > float(values[day]):
        values[day] = total
    old_quality = quality.get(day, {})
    if not old_quality or new_quality['observations'] >= old_quality.get('observations', 0):
        quality[day] = new_quality
    save(values_path, values)
    save(quality_path, quality)


def check():
    for folder in ('P_daily', 'P_daily_quality'):
        files = sorted((OUT / folder).glob('*.json'))
        data = {k: v for path in files for k, v in load(path).items()}
        print(f'{folder}: {len(data)} days; {min(data) if data else "—"} to {max(data) if data else "—"}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='2023-01-01')
    parser.add_argument('--end', default=date.today().isoformat())
    parser.add_argument('--delay', type=float, default=1.5)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.check:
        check()
        return
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if start > end:
        parser.error('--start must not be after --end')
    print('Backfilling daily rainfall from Ecowitt rainfall.daily; timezone:', TZ)
    print('Writes ONLY P_daily and P_daily_quality. Existing P_1h and ARPA data are untouched.')
    day = start
    while day <= end:
        try:
            # Request local midnight-to-midnight in UTC-naive API timestamps.
            left = datetime.combine(day, datetime.min.time(), tzinfo=TZ).astimezone(timezone.utc).replace(tzinfo=None)
            right = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=TZ).astimezone(timezone.utc).replace(tzinfo=None)
            groups = daily_observations(query(left, right))
            samples = groups.get(day.isoformat(), [])
            if samples:
                merge_day(day.isoformat(), samples)
                print(f'{day} OK raw={len(samples)} daily_max={max(v for _, v in samples):.2f} mm (unverified)', flush=True)
            else:
                print(f'{day} NO DAILY DATA', flush=True)
        except Exception as exc:
            print(f'{day} FAILED: {type(exc).__name__}: {exc}. Previous days retained.', flush=True)
            raise SystemExit(1)
        day += timedelta(days=1)
        if day <= end:
            time.sleep(max(args.delay, 0))
    check()


if __name__ == '__main__':
    main()
