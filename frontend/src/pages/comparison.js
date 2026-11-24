import {feedback, field} from '../components/common/fields.js';
import {empty, metrics, panel, pill} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {STATUS} from '../constants/enums.js';
import {handler} from '../hooks/action.js';
import {session} from '../stores/session.js';
import {workspace} from '../stores/workspace.js';
import {button, el, link, p} from '../utils/dom.js';
import {date} from '../utils/format.js';

function launchForm(spec, message, refresh) {
  const submit = button('发起历史比较', {type:'submit', class:'primary', 'data-testid':'start-comparison'});
  const params = spec.params.filter(item => ['report_day','lead_days_a','lead_days_b','horizon_days','min_coverage_percent'].includes(item.key));
  return el('form', {class:'fields', 'data-testid':'comparison-form', onSubmit:handler(submit, message, async event => {
    const data = new FormData(event.target);
    const dataset = workspace.datasets.find(item => String(item.id) === String(data.get('dataset_id')));
    if (!dataset) throw new Error('请先导入数据批次');
    await workspace.startComparison({
      dataset_id:dataset.id, dataset_name:dataset.name,
      name:data.get('name') || `历史比较 · ${data.get('report_day')}`,
      params:Object.fromEntries(params.map(param => [param.key, data.get(param.key)])),
    });
    await refresh();
  })}, datasetSelect(workspace.datasets), field({key:'name', label:'比较名称', type:'string', required:false, max_length:120}, '历史比较'),
    el('div', {class:'form-grid'}, params.map(item => field(item))), el('div', {class:'actions'}, submit), message);
}

function datasetSelect(datasets) {
  return el('label', {class:'field', for:'comparison-dataset'}, el('span', {}, '数据批次'),
    el('select', {id:'comparison-dataset', name:'dataset_id', required:true}, datasets.map(item =>
      el('option', {value:item.id}, `${item.name} · ${item.row_count} 行`))));
}

function boundsPanel(detail) {
  const result = detail.comparison || {};
  const bounds = result.bounds || {};
  const missed = result.missed || {};
  return panel('漏警台数之差（两套方案同一组起点）', metrics([
    {label:'下界（A−B）', value:bounds.lower ?? '—', detail:'逐台最小差值累加'},
    {label:'上界（A−B）', value:bounds.upper ?? '—', detail:'逐台最大差值累加'},
    {label:'计入器具', value:bounds.counted ?? 0, detail:'查出超差、参与差值'},
    {label:'方案 A 漏警', value:`${missed.a?.min ?? '—'} ~ ${missed.a?.max ?? '—'}`, detail:`提前 ${detail.lead_days.a} 天`},
    {label:'方案 B 漏警', value:`${missed.b?.min ?? '—'} ~ ${missed.b?.max ?? '—'}`, detail:`提前 ${detail.lead_days.b} 天`},
    {label:'未查出超差', value:detail.unsolved_count, detail:'单列，不计入差值'},
  ]));
}

function assetTable(result) {
  return table([
    {key:'asset_id', label:'器具编号'}, {key:'owner', label:'责任班组'},
    {label:'可能起点区间', render:row => `${row.window_from} ~ ${row.window_to}`},
    {label:'方案 A 首次预警', render:row => row.warning_a || '未预警'},
    {label:'方案 B 首次预警', render:row => row.warning_b || '未预警'},
    {label:'漏警差（A−B）', render:row => `${row.delta.lower > 0 ? '+' : ''}${row.delta.lower} ~ ${row.delta.upper > 0 ? '+' : ''}${row.delta.upper}`},
    {label:'晚到记录', render:row => row.late_records.length},
  ], result.assets || [], {caption:'逐台漏警差值', empty:'尚无可比较的记录。'});
}

function unsolvedTable(result) {
  return table([
    {key:'asset_id', label:'器具编号'}, {key:'owner', label:'责任班组'},
    {key:'reason', label:'原因'}, {key:'latest_shift', label:'最近检查班次'},
    {key:'latest_result', label:'最近结果'},
  ], result.unsolved || [], {caption:'未查出超差（单列）', empty:'所有器具都查出过超差。'});
}

async function shiftEvidence(comparisonId, asset) {
  const rows = await workspace.comparisonShifts(comparisonId, asset);
  return table([
    {key:'asset_id', label:'器具编号'}, {key:'shift', label:'班次'},
    {key:'certificate_id', label:'当班证书'}, {key:'expires_on', label:'到期日'},
    {key:'days_remaining', label:'剩余天数'},
    {label:'方案 A', render:row => row.scheme_a ? '预警' : '—'},
    {label:'方案 B', render:row => row.scheme_b ? '预警' : '—'},
    {key:'inspection_result', label:'检查结果'}, {key:'recorded_on', label:'录入日期'},
    {label:'是否晚到', render:row => row.late ? '晚到' : '—'},
  ], rows, {caption:'逐班还原的证据', empty:'没有逐班证据。'});
}

export async function comparisonPage(route, refresh) {
  const {spec, datasets, comparisons = []} = workspace;
  const message = feedback();
  const jobs = await workspace.comparisonJobs();
  const id = route.id || comparisons[0]?.id;
  const detail = id ? await workspace.comparison(id) : null;

  const jobList = table([
    {label:'任务', render:row => row.name},
    {label:'状态', render:row => pill(STATUS[row.status], row.status)},
    {label:'重算器具', render:row => row.recomputed.length ? row.recomputed.join('、') : '整批首次计算'},
    {label:'时间', render:row => date(row.finished_at || row.created_at)},
    {label:'结果', render:row => row.comparison_id ? link(`比较 ${row.comparison_id}`, `#comparison/${row.comparison_id}`) : (row.error || '—')},
  ], jobs, {caption:'比较任务', empty:'尚未发起历史比较。'});

  const published = table([
    {label:'比较', render:row => link(`${row.dataset_name} · ${row.report_day}`, `#comparison/${row.id}`)},
    {label:'提前量', render:row => `A ${row.lead_days.a} / B ${row.lead_days.b}`},
    {label:'漏警差', render:row => row.bounds ? `${row.bounds.lower} ~ ${row.bounds.upper}` : '—'},
    {label:'版本', render:row => `v${row.version} · 批次 ${row.revision}`},
    {label:'未查出超差', render:row => row.unsolved_count},
    {label:'发布', render:row => date(row.published_at)},
  ], comparisons, {caption:'已发布比较', empty:'发布后会在此显示。'});

  const backfill = detail && session.canWrite ? button('补录后重算', {class:'quiet', onClick:event =>
    handler(event.currentTarget, message, async () => {
      await workspace.backfill(detail.id);
      await refresh();
    })(event)}) : null;

  const detailPanel = detail ? panel(`${detail.dataset_name} · ${detail.report_day}`,
    boundsPanel(detail),
    p((detail.comparison?.note) || '暂无说明。', 'intro-copy'),
    backfill, message,
    panel('逐台漏警差值', assetTable(detail.comparison || {})),
    panel('未查出超差', unsolvedTable(detail.comparison || {})),
    panel('逐班证据', el('div', {class:'two-col'},
      el('label', {class:'field', for:'comparison-asset'}, el('span', {}, '按器具查看'),
        el('select', {id:'comparison-asset', onChange: async event => {
          const target = document.getElementById('comparison-evidence');
          if (target) target.replaceChildren(await shiftEvidence(detail.id, event.target.value));
        }},
          el('option', {value:''}, '全部器具'),
          (detail.comparison?.assets || []).map(asset => el('option', {value:asset.asset_id}, asset.asset_id)))),
      el('div', {id:'comparison-evidence'}, await shiftEvidence(detail.id, '')))))
    : empty('还没有可查看的比较结果。先在上方发起一次历史比较。');

  const form = session.canWrite && datasets.length ? panel('发起比较', p('逐班还原当时收到的证书，晚到记录只补实绩。','subtle'), launchForm(spec, message, refresh)) : null;

  return el('div', {class:'two-col'},
    el('div', {class:'wide-panel'}, detailPanel, panel('比较任务', jobList)),
    el('aside', {class:'sidebar-panel'}, form, panel('已发布比较', published),
      panel('口径', el('ul', {class:'method-list'}, spec.methodology.slice(4).map(text => el('li', {}, text))))));
}
