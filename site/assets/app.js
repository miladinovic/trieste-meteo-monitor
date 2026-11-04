const $=id=>document.getElementById(id);let stations=[],sensors={},shown=[];
const names={T:'Temperature',U:'Humidity',B:'Pressure',Vv:'Wind speed',VvMax:'Maximum wind speed',P_1h:'Hourly rainfall',Prec_5_min:'Rainfall (5-minute window)',Prec_60_min:'Rainfall (60-minute window)',Prec_24_ore:'Rainfall (24-hour window)',Dv:'Wind direction'};
const rainCode=c=>c==='P_1h';
const allowed=['T','U','P_1h','B','Vv','VvMax'];
const fmt=d=>{let [y,m,day]=d.split('-');return `${day}/${m}/${y}`};
const fmtTime=t=>{const [date,time]=t.split(/[ T]/);return `${fmt(date)}${time?' · '+time.slice(0,5):''}`};
const plotDate=t=>t.length===7?t+'-01':t.replace(' ','T');
const mobile=()=>window.matchMedia('(max-width: 600px)').matches;
const chartLayout=(unit,monthly=false)=>{const m=mobile();return {autosize:true,height:m?320:440,margin:{t:18,l:m?47:66,r:m?8:24,b:m?52:65},paper_bgcolor:'#fff',plot_bgcolor:'#fff',font:{size:m?11:13},xaxis:{title:m?'':'Date',type:'date',tickformat:monthly?'%b %Y':undefined,nticks:m?4:9,automargin:true,gridcolor:'#edf2f5',tickangle:0,fixedrange:m},yaxis:{title:m?'':unit,automargin:true,nticks:m?5:8,gridcolor:'#edf2f5'},dragmode:m?false:'zoom',hovermode:'x unified',hoverlabel:{namelength:30},showlegend:false}};
// On phones, make Plotly charts read-only so swipes scroll the page instead of zooming/panning.
// Desktop charts retain their normal hover and drag interactions.
const plotConfig=()=>({responsive:true,displaylogo:false,displayModeBar:false,scrollZoom:false,staticPlot:false,doubleClick:false});
async function json(url){const u=new URL(url,location.href);u.searchParams.set('_fresh',String(Date.now()));const r=await fetch(u.toString(),{cache:'no-store'});if(!r.ok)throw Error(`HTTP ${r.status}`);return r.json()}
function selectedStation(){return stations.find(x=>String(x.id)===$('station').value)}
const ECO='ecowitt-roiano';
function isEco(id){return String(id)===ECO}
function dataPath(st,s,year){return isEco(st.id)?`data/ecowitt/${s.code}/${year}.json`:`data/history/${st.id}/${s.id}/${year}.json`}
function populateSensors(preferredCode=null){let list=sensors[$('station').value]||[];list=list.filter(s=>s.id!=null&&allowed.includes(s.code)&&s.status!=='D');list.sort((a,b)=>{const p=allowed;return (p.indexOf(a.code)<0?100:p.indexOf(a.code))-(p.indexOf(b.code)<0?100:p.indexOf(b.code))});$('sensor').innerHTML='';for(let s of list){let o=document.createElement('option');o.value=s.id;o.textContent=`${names[s.code]||s.name||s.code} · ${s.code} (${s.unit})`;$('sensor').append(o)}if(preferredCode){const match=list.find(s=>s.code===preferredCode);if(match)$('sensor').value=String(match.id)}let st=selectedStation();$('station-info').textContent=st?(isEco(st.id)?'Ecowitt · manually uploaded data · timestamps in UTC':`${st.name} · ${st.alt??'?'} m altitude · station #${st.id}`):'No stations available';if(st&&st.lat!=null&&st.lon!=null){$('map').href=`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(st.lat+','+st.lon)}`;$('map').hidden=false}else $('map').hidden=true}
function aggregate(rows,mode,isRain){if(mode==='hourly')return rows.map(([t,v])=>[t,v]);let groups=new Map();for(let [t,v] of rows){let key=mode==='daily'?t.slice(0,10):t.slice(0,7);let g=groups.get(key)||{sum:0,n:0};g.sum+=v;g.n++;groups.set(key,g)}return [...groups].map(([k,g])=>[k,isRain?g.sum:g.sum/g.n])}
let requestSerial=0;
// Ecowitt rainfall totals use the daily counter archive, never the rolling 1_hour archive.
async function loadRows(st,s,from,to){
 const code=isEco(st.id)&&rainCode(s.code)?'P_daily':s.code;
 const rows=[];let missingYears=0;
 for(let y=Number(from.slice(0,4));y<=Number(to.slice(0,4));y++){
  const path=isEco(st.id)?`data/ecowitt/${code}/${y}.json`:dataPath(st,s,y);
  try{const obj=await json(path);rows.push(...Object.entries(obj))}
  catch(e){missingYears++;if(!String(e).includes('404'))console.warn(e)}
 }
 const valid=rows.filter(([t,v])=>t.slice(0,10)>=from&&t.slice(0,10)<=to&&v!==null&&v!==''&&Number.isFinite(Number(v))&&(!rainCode(s.code)||Number(v)>=0))
   .map(([t,v])=>[t,Number(v)]).sort((a,b)=>a[0].localeCompare(b[0]));
 return {rows:valid,missingYears};
}
function dailyRainAggregate(rows,mode){
 if(mode==='monthly')return aggregate(rows,'monthly',true);
 return rows; // Ecowitt has daily totals, not hourly increments.
}
function rainCoverage(rows,from,to){
 const start=new Date(from+'T00:00:00Z'),end=new Date(to+'T00:00:00Z');
 const days=Math.round((end-start)/86400000)+1;
 return `${new Set(rows.map(r=>r[0].slice(0,10))).size} of ${days} days with observations`;
}
async function show(){
 const requestId=++requestSerial,st=selectedStation();
 const s=(sensors[$('station').value]||[]).find(x=>String(x.id)===$('sensor').value);
 if(!st||!s)return;
 $('notice').textContent='Loading cached observations…';
 const rain=rainCode(s.code),ecoRain=rain&&isEco(st.id),from=$('start').value,to=$('end').value;
 $('rain-comparison-section').hidden=!rain;
 if(from>to){$('notice').textContent='Start date must be before end date.';return}
 const result=await loadRows(st,s,from,to);if(requestId!==requestSerial)return;
 const rows=result.rows,mode=$('resolution').value;
 shown=ecoRain?dailyRainAggregate(rows,mode):aggregate(rows,mode,rain);
 const extrema=$('temperature-extremes');extrema.hidden=s.code!=='T';
 if(s.code==='T'){
  if(rows.length){const lo=rows.reduce((a,b)=>b[1]<a[1]?b:a),hi=rows.reduce((a,b)=>b[1]>a[1]?b:a);
   $('temp-min').textContent=lo[1].toFixed(1)+' °C';$('temp-min-date').textContent=fmtTime(lo[0]);
   $('temp-max').textContent=hi[1].toFixed(1)+' °C';$('temp-max-date').textContent=fmtTime(hi[0]);}
  else{$('temp-min').textContent=$('temp-max').textContent='—';$('temp-min-date').textContent=$('temp-max-date').textContent='No observations'}
 }
 const unit=s.unit||'',label=ecoRain?'Daily rainfall':names[s.code]||s.name||s.code;
 $('chart-title').textContent=`${label} · ${st.name}`;
 $('latest').textContent=rows.length?`${rows.at(-1)[1].toFixed(1)} ${unit}`:'—';
 $('stat-label').textContent=rain?'Rainfall total':'Mean of observations';
 const total=rows.reduce((a,r)=>a+r[1],0);
 $('summary').textContent=rows.length?`${(rain?total:total/rows.length).toFixed(1)} ${unit}`:'—';
 $('count').textContent=rows.length.toLocaleString();
 const coverage=rain?` · ${rainCoverage(rows,from,to)}`:'';
 const caveat=ecoRain?' · Ecowitt daily counter maxima; historical totals unverified, potentially incomplete. Hourly view shows daily totals.':rain?' · Sum of stored hourly increments; check data coverage.':' · Arithmetic mean of available readings.';
 $('notice').textContent=rows.length?`${rows.length} observations · ${fmt(from)} – ${fmt(to)}${coverage}${caveat}`:'No cached observations for this period. Missing data are not zero rainfall.';
 if(rain){if(ecoRain)showEcoRainComparison(from,to,requestId);else showRainComparison(st.id)}
 if(!window.Plotly){$('notice').textContent+=' (Plotly library unavailable.)';return}
 const labels=shown.map(r=>plotDate(r[0])),vals=shown.map(r=>r[1]);
 const type=rain&&(ecoRain||mode!=='hourly')?'bar':'scatter';
 const trace={x:labels,y:vals,type,mode:type==='scatter'?'lines':undefined,
  line:{color:'#147b92',width:mobile()?1.7:2},marker:{color:'#147b92'},name:label,connectgaps:false,
  hovertemplate:'%{x|%d %b %Y}<br>%{y:.2f} '+unit+'<extra></extra>'};
 if(requestId===requestSerial)await Plotly.react('chart',[trace],chartLayout(unit,mode==='monthly'),plotConfig());
}
async function showEcoRainComparison(from,to,serial){
 const note=$('rain-comparison-note');note.textContent='Loading Ecowitt monthly rainfall…';
 try{
  const data=[];
  for(let y=2023;y<=Number(to.slice(0,4));y++){
   try{data.push(...Object.entries(await json(`data/ecowitt/P_daily/${y}.json`)))}catch(e){if(!String(e).includes('404'))console.warn(e)}
  }
  if(serial!==requestSerial)return;
  const months=new Map();for(const [day,v] of data){if(v===null||v===''||!Number.isFinite(Number(v))||Number(v)<0)continue;
   const key=day.slice(0,7);const cur=months.get(key)||{total:0,n:0};cur.total+=Number(v);cur.n++;months.set(key,cur)}
  const years=[...new Set([...months.keys()].map(k=>k.slice(0,4)))].sort();
  if(!years.length){note.textContent='No Ecowitt daily rainfall archive found.';if(window.Plotly)Plotly.purge('rain-comparison');return}
  const labels=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const traces=years.map(year=>({name:year,type:'bar',x:labels,
   y:labels.map((_,i)=>months.get(`${year}-${String(i+1).padStart(2,'0')}`)?.total??null),
   customdata:labels.map((_,i)=>months.get(`${year}-${String(i+1).padStart(2,'0')}`)?.n??null),
   hovertemplate:'%{x} '+year+': %{y:.1f} mm<br>%{customdata} observed days<extra></extra>'}));
  note.textContent='Ecowitt daily-counter maxima (unverified). Partial months may underestimate rainfall; missing months remain blank.';
  if(window.Plotly)await Plotly.react('rain-comparison',traces,rainComparisonLayout(),plotConfig());
 }catch(e){note.textContent='Unable to load Ecowitt daily rainfall: '+e.message}
}
function rainComparisonLayout(){return {autosize:true,height:mobile()?350:430,dragmode:mobile()?false:'zoom',barmode:'group',
 margin:{t:20,l:mobile()?45:65,r:10,b:mobile()?90:65},yaxis:{title:mobile()?'':'Rainfall (mm)',automargin:true,fixedrange:mobile()},
 xaxis:{title:mobile()?'':'Month',automargin:true,fixedrange:mobile(),tickfont:{size:mobile()?10:12}},
 legend:{orientation:'h',x:0,y:-0.23,font:{size:11}},paper_bgcolor:'#fff',plot_bgcolor:'#fff'}}

async function showRainComparison(stationId){
 const note=$('rain-comparison-note');note.textContent='Loading monthly rainfall comparison…';
 try{
  const cache=await json('data/rainfall_monthly.json');const months=cache.stations?.[stationId]?.months||{};
  const years=[...new Set(Object.keys(months).map(k=>k.slice(0,4)))].sort();
  if(!years.length){note.textContent='No historical rainfall data collected yet.';Plotly.purge('rain-comparison');return}
  const labels=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const traces=years.map(year=>({name:year,type:'bar',x:labels,y:labels.map((_,i)=>months[`${year}-${String(i+1).padStart(2,'0')}`]?.total??null),customdata:labels.map((_,i)=>months[`${year}-${String(i+1).padStart(2,'0')}`]?.observations??null),hovertemplate:'%{x} '+year+': %{y:.1f} mm<br>%{customdata} readings<extra></extra>'}));
  note.textContent='Available months since January 2023. Partial months are shown as collected, not as complete monthly totals; missing months remain blank.';
  if(window.Plotly)Plotly.react('rain-comparison',traces,{autosize:true,height:mobile()?350:430,dragmode:mobile()?false:'zoom',barmode:'group',margin:{t:20,l:mobile()?45:65,r:10,b:mobile()?90:65},yaxis:{title:mobile()?'':'Rainfall (mm)',automargin:true,fixedrange:mobile()},xaxis:{title:mobile()?'':'Month',automargin:true,fixedrange:mobile(),tickfont:{size:mobile()?10:12}},legend:{orientation:'h',x:0,y:-0.23,font:{size:11}},paper_bgcolor:'#fff',plot_bgcolor:'#fff'},plotConfig());
 }catch(e){note.textContent='Monthly comparison cache not yet available. Run the updated collector to generate it.'}
}
function exportCsv(){const s=(sensors[$('station').value]||[]).find(x=>String(x.id)===$('sensor').value);const lines=['timestamp,value,unit',...shown.map(([t,v])=>`${t},${v},"${(s?.unit||'').replaceAll('"','""')}"`)];let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([lines.join('\n')],{type:'text/csv;charset=utf-8'}));a.download=`fvg_${$('station').value}_${$('sensor').value}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
async function init(){try{[stations,sensors]=await Promise.all([json('data/stations.json'),json('data/sensors.json')]);let state=await json('data/collection_state.json').catch(()=>({}));$('updated').textContent=state.last_updated?`Last collection: ${new Date(state.last_updated).toLocaleString('it-IT')}`:'Historical collection not started';$('station').innerHTML='';stations=stations.filter(st=>![502,625].includes(Number(st.id))&& !/trieste marea|trieste nautico cae/i.test(st.name||''));stations.push({id:ECO,name:'Ecowitt Roiano',status:'N'});sensors[ECO]=allowed.map((code,i)=>({id:'eco-'+code,code,unit:({T:'°C',U:'%',P_1h:'mm',B:'hPa',Vv:'m/s',VvMax:'m/s'})[code],status:'O'}));for(let st of stations){let o=document.createElement('option');o.value=st.id;o.textContent=st.name;$('station').append(o)}if(stations.some(x=>x.id===504))$('station').value='504';$('end').value=new Date().toISOString().slice(0,10);$('start').value=new Date(Date.now()-30*86400000).toISOString().slice(0,10);populateSensors();let activeSensorCode=(sensors[$('station').value]||[]).find(s=>String(s.id)===$('sensor').value)?.code||null;initComparison();$('station').addEventListener('change',()=>{populateSensors(activeSensorCode);activeSensorCode=(sensors[$('station').value]||[]).find(s=>String(s.id)===$('sensor').value)?.code||null;show()});$('sensor').addEventListener('change',()=>{activeSensorCode=(sensors[$('station').value]||[]).find(s=>String(s.id)===$('sensor').value)?.code||null;show()});$('show').addEventListener('click',show);$('resolution').addEventListener('change',show);$('csv').addEventListener('click',exportCsv);show()}catch(e){$('notice').textContent='Unable to load station metadata: '+e.message}}init();

let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(window.Plotly){for(const id of ['chart','rain-comparison','compare-chart']){const el=$(id);if(el?.data?.length)Plotly.Plots.resize(el)}}},180)});

async function stationRows(st,code,from,to){
 const sensor=(sensors[String(st.id)]||[]).find(x=>x.code===code);
 return sensor?(await loadRows(st,sensor,from,to)).rows:[];
}
function initComparison(){for(const id of ['compare-a','compare-b']){const el=$(id);el.innerHTML='';for(const st of stations){const opt=document.createElement('option');opt.value=st.id;opt.textContent=st.name;el.append(opt)}}$('compare-a').value=stations.some(s=>s.id===504)?'504':String(stations[0]?.id);$('compare-b').value=ECO;for(const code of allowed){const opt=document.createElement('option');opt.value=code;opt.textContent=names[code];$('compare-sensor').append(opt)}$('compare-show').addEventListener('click',compareStations)}
let compareSerial=0;
async function compareStations(){
 const serial=++compareSerial,a=stations.find(s=>String(s.id)===$('compare-a').value),b=stations.find(s=>String(s.id)===$('compare-b').value);
 const code=$('compare-sensor').value,from=$('start').value,to=$('end').value,note=$('compare-note');
 if(!a||!b||from>to){note.textContent='Choose valid stations and dates.';return}
 if(String(a.id)===String(b.id)){note.textContent='Select two different stations.';return}
 note.textContent='Loading both stations…';
 const [ra,rb]=await Promise.all([stationRows(a,code,from,to),stationRows(b,code,from,to)]);
 if(serial!==compareSerial)return;
 const rain=code==='P_1h',mode=$('resolution').value;
 // Rainfall comparison uses daily/monthly totals, never an hourly-vs-daily mixture.
 const compareMode=rain?(mode==='monthly'?'monthly':'daily'):mode;
 const traces=[[a,ra],[b,rb]].map(([st,rows])=>{
  const agg=aggregate(rows,compareMode,rain);
  return {type:'scatter',mode:'lines+markers',name:st.name,x:agg.map(x=>plotDate(x[0])),y:agg.map(x=>x[1]),connectgaps:false};
 });
 note.textContent=rain?`${a.name}: ${ra.length} readings · ${b.name}: ${rb.length} readings. Daily/monthly rainfall comparison; Ecowitt daily totals are unverified and incomplete periods may underestimate rainfall. ARPA hours and Ecowitt local calendar days may differ.`:
 `${a.name}: ${ra.length} observations · ${b.name}: ${rb.length} observations. Missing readings are not zero.`;
 if(window.Plotly)await Plotly.react('compare-chart',traces,{...chartLayout((sensors[String(a.id)]||[]).find(x=>x.code===code)?.unit||''),showlegend:true,legend:{orientation:'h',y:-0.24},margin:{t:20,l:mobile()?45:65,r:10,b:mobile()?85:70}},plotConfig());
}
