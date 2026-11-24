import {plot} from '../components/common/chart.js';
import {feedback} from '../components/common/fields.js';
import {empty, metrics, panel, pill} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {REVIEW, STATUS} from '../constants/enums.js';
import {handler, poll} from '../hooks/action.js';
import {workspace} from '../stores/workspace.js';
import {button, el, h, link, p} from '../utils/dom.js';
import {date, value} from '../utils/format.js';

const EVIDENCE_TITLE = '逐班还原的证据（当时证书、预警与检查依据）';

function evidenceTable(rows) {
  return table([
    {key:'asset_id',label:'器具编号'}, {key:'shift',label:'班次'},
    {key:'certificate_id',label:'当班证书'}, {key:'expires_on',label:'到期日'},
    {key:'days_remaining',label:'剩余天数'},
    {label:'方案 A',render:row => row.scheme_a === '预警' ? '预警' : '—'},
    {label:'方案 B',render:row => row.scheme_b === '预警' ? '预警' : '—'},
    {key:'inspection_result',label:'检查结果'}, {key:'recorded_on',label:'录入日期'},
    {label:'是否晚到',render:row => row.late === '晚到' ? '晚到' : '—'},
  ], rows, {caption:'预警与检查依据', empty:'没有可查的依据。'});
}

function evidenceLookup(result) {
  const source = (result.tables || []).find(item => item.title === EVIDENCE_TITLE);
  if (!source || !source.rows.length) return null;
  const shifts = source.rows;
  const byAsset = new Map();
  for (const row of shifts) {
    if (!byAsset.has(row.asset_id)) byAsset.set(row.asset_id, []);
    byAsset.get(row.asset_id).push(row);
  }
  const picker = el('select',{id:'evidence-asset','aria-label':'按器具查看证据'},
    el('option',{value:''},'全部器具'),
    [...byAsset.keys()].map(asset => el('option',{value:asset},asset)));
  const body = el('div',{id:'evidence-body'}, evidenceTable(shifts));
  picker.addEventListener('change', () =>
    body.replaceChildren(evidenceTable(picker.value ? byAsset.get(picker.value) || [] : shifts)));
  return panel('预警与检查依据',
    p('逐班还原当时的证书；晚到记录只补实绩，不改当班预警。可以按器具回查依据。','subtle'),
    el('label',{class:'field run-picker',for:'evidence-asset'},el('span',{},'按器具查看'),picker), body);
}

export async function results(route, refresh) {
  const {spec,runs,datasets} = workspace;
  const id = route.id || runs[0]?.id;
  if (!id) return panel(spec.pages[3],empty('还没有可查看的运行结果。','#run','前往运行'));
  const job = await workspace.getRun(id);
  const source = datasets.find(item => item.id === job.dataset_id);
  const message = feedback();
  const finished = item => item.status === 'complete' || item.status === 'failed';
  if (!finished(job)) {
    const original = location.hash;
    const status = el('p',{role:'status'},'后台正在计算，完成后会自动展示。');
    poll(()=>workspace.getRun(id),finished,()=>location.hash===original)
      .then(result=>{if (result && status.isConnected && location.hash===original) refresh();
        else if(status.isConnected) status.textContent='仍在执行，请点击刷新检查。';})
      .catch(error=>{if(status.isConnected) status.textContent=error.message;});
    return panel(job.name,pill(STATUS[job.status],job.status),status,button('刷新',{class:'quiet',onClick:refresh}));
  }
  const download = button('下载结果 CSV',{class:'quiet','data-testid':'export',onClick:event=>
    handler(download,message,()=>workspace.download(`/runs/${job.id}/export`,`${spec.short_name}-${job.id}.csv`))(event)});
  const history = el('label',{class:'field run-picker',for:'run-picker'},el('span',{},'切换运行记录'),
    el('select',{id:'run-picker',onChange:event=>{location.hash=`#results/${event.target.value}`;}},
      (runs.some(item=>item.id===job.id) ? runs : [job,...runs]).map(item=>el('option',{value:item.id,selected:item.id===job.id},item.name))));
  const result = job.result;
  const analysis = result ? el('section',{class:'analysis','data-testid':'analysis-complete'},
    el('div',{class:'result-head'},p(job.name,'eyeline'),h(2,result.headline),p(result.note,'intro-copy'),
      el('div',{class:'actions'},pill(STATUS[job.status],job.status),download,message)),
    metrics(result.metrics),
    result.charts.map(plot),
    (result.sections || []).map(item=>panel(item.title,p(item.text))),
    result.tables.map(item=>panel(item.title,table(item.columns,item.rows,{caption:item.title}))),
    evidenceLookup(result))
    : panel(job.name,pill(STATUS[job.status],job.status),p(job.error,'feedback'),link('返回调整参数',`#run/${job.dataset_id}`,{class:'quiet'}));
  const inputs = spec.params.map(param=>el('div',{},el('dt',{},param.label),el('dd',{},value(job.params[param.key]))));
  return el('div',{},el('div',{class:'two-col'},el('div',{class:'wide-panel'},analysis),
    el('aside',{class:'sidebar-panel'},panel('运行来源',history,
      source && link(source.name,`#inputs/${source.id}`),p(date(job.finished_at),'subtle'),
      el('dl',{class:'dictionary'},inputs)),
    result && panel(spec.decision, pill(REVIEW[job.review],job.review),
      link('打开复核记录',`#review/${job.id}`,{class:'quiet'})))));
}
