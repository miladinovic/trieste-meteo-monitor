#!/usr/bin/env python3
"""Manual Ecowitt cloud downloader; stdlib only. Credentials via environment, never committed.

Example:
 ECOWITT_APPLICATION_KEY=... ECOWITT_API_KEY=... python3 scripts/ecowitt_local.py --start 2026-10-01 --end 2026-11-03
 python3 scripts/ecowitt_local.py --check

API availability/retention depends on the Ecowitt account. Download in daily windows.
"""
import argparse, json, os, time, urllib.parse, urllib.request
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'site'/'data'/'ecowitt'
MAC=os.getenv('ECOWITT_DEVICE_MAC','7C:87:CE:B7:FF:52')
FIELDS={'T':('outdoor','temperature'),'U':('outdoor','humidity'),'B':('pressure','relative'),'Vv':('wind','wind_speed'),'VvMax':('wind','wind_gust'),'P_1h':('rainfall','1_hour')}
# Ecowitt historic endpoint returns a dictionary keyed by UNIX timestamp for each sensor.
API='https://api.ecowitt.net/api/v3/device/history'

def read(path):
 try:return json.loads(path.read_text())
 except (OSError,ValueError):return {}

def save(path, obj):
 path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':')));tmp.replace(path)

def query(start,end):
 app=os.environ.get('ECOWITT_APPLICATION_KEY');key=os.environ.get('ECOWITT_API_KEY')
 if not app or not key:raise RuntimeError('Set ECOWITT_APPLICATION_KEY and ECOWITT_API_KEY environment variables.')
 params={'application_key':app,'api_key':key,'mac':MAC,'start_date':start.strftime('%Y-%m-%d %H:%M:%S'),'end_date':end.strftime('%Y-%m-%d %H:%M:%S'),'call_back':'outdoor,pressure,wind,rainfall','cycle_type':'auto','temp_unitid':1,'pressure_unitid':3,'wind_speed_unitid':7,'rainfall_unitid':12}
 # Never print the URL: it includes secrets.
 req=urllib.request.Request(API+'?'+urllib.parse.urlencode(params),headers={'User-Agent':'TriesteMeteo/1.0'})
 for attempt in range(4):
  try:
   with urllib.request.urlopen(req,timeout=55) as response: payload=json.load(response)
   if str(payload.get('code','0')) not in ('0','200'):raise RuntimeError('Ecowitt response code '+str(payload.get('code'))+': '+str(payload.get('msg','unknown error')))
   return payload.get('data') or {}
  except Exception:
   if attempt==3:raise
   time.sleep(2**attempt)

def points(data,section,field):
 node=data.get(section,{}) if isinstance(data,dict) else {}
 node=node.get(field,{}) if isinstance(node,dict) else {}
 if not isinstance(node,dict):return {}
 node=node.get('list',node)
 if not isinstance(node,dict):return {}
 out={}
 for stamp,reading in node.items():
  try:
   if isinstance(reading,dict):reading=reading.get('value')
   if reading in ('',None):continue
   val=float(reading)
   if not (-1e9<val<1e9):continue
   ts=datetime.fromtimestamp(int(stamp),timezone.utc).strftime('%Y-%m-%d %H:%M:%S') if str(stamp).isdigit() else str(stamp).replace('T',' ')[:19]
   datetime.fromisoformat(ts)
   out[ts]=val
  except (TypeError,ValueError,OverflowError):continue
 return out

def rainfall_increments(data):
 """Extract Ecowitt rainfall.1_hour (rolling previous-hour total, mm).

 Retain only one reading per UTC clock hour, nearest to the hour boundary.
 A rolling 1-hour amount must NEVER be summed at 5-minute resolution.
 Values sampled at HH:00 represent the preceding hour (HH-1:00 to HH:00).
 """
 vals=points(data,'rainfall','1_hour')
 by_hour={}
 for stamp,value in vals.items():
  try:
   dt=datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
   # A reading near HH:00 describes the preceding 60 minutes.
   boundary=dt.replace(minute=0,second=0,microsecond=0)
   if dt.minute>=55:boundary+=timedelta(hours=1)
   distance=abs((dt-boundary).total_seconds())
   if distance>5*60:continue
   key=boundary.strftime('%Y-%m-%d %H:%M:%S')
   if key not in by_hour or distance<by_hour[key][0]:by_hour[key]=(distance,value)
  except (ValueError,TypeError):continue
 return {key:val for key,(_,val) in by_hour.items()}

def check():
 print('Ecowitt data audit (UTC timestamps; P_1h sampled once at each UTC hour boundary)')
 for code in FIELDS:
  total=0;first=last=None
  for p in sorted((OUT/code).glob('*.json')):
   obj=read(p)
   for t,v in obj.items():
    try:float(v);datetime.fromisoformat(t)
    except (ValueError,TypeError):continue
    total+=1;first=min(first,t) if first else t;last=max(last,t) if last else t
  print(f'{code:6} {total:>8} observations  {first or "—"} → {last or "—"}')

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--start',default=(date.today()-timedelta(days=7)).isoformat())
 parser.add_argument('--end',default=date.today().isoformat())
 parser.add_argument('--delay',type=float,default=1.5)
 parser.add_argument('--check',action='store_true')
 a=parser.parse_args()
 if a.check:check();return
 begin=date.fromisoformat(a.start);end=date.fromisoformat(a.end)
 if end<begin:parser.error('--end must be >= --start')
 print('Downloading Ecowitt data for',MAC,'from',begin,'to',end,'(inclusive).')
 print('API keys will not be printed. Already saved readings are merged, not overwritten.')
 day=begin
 while day<=end:
  try:
   data=query(datetime.combine(day,datetime.min.time()),datetime.combine(day+timedelta(days=1),datetime.min.time()))
   for code,(section,field) in FIELDS.items():
    vals=rainfall_increments(data) if code=='P_1h' else points(data,section,field)
    if not vals:continue
    for year in set(t[:4] for t in vals):
     p=OUT/code/(year+'.json');existing=read(p);existing.update({t:v for t,v in vals.items() if t.startswith(year)});save(p,dict(sorted(existing.items())))
   print(day,'OK',', '.join(f'{c}:{len(rainfall_increments(data) if c=="P_1h" else points(data,*f))}' for c,f in FIELDS.items()))
  except Exception as e:
   print(day,'FAILED:',e,'— stop; rerun this date later.');raise SystemExit(1)
  day+=timedelta(days=1);time.sleep(max(0,a.delay))
 check()
if __name__=='__main__':main()
