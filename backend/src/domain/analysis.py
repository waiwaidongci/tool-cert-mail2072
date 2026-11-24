"""校准证书的报告日快照、器具处置清单与分发判定。"""

from collections import Counter, defaultdict
from datetime import date

from . import comparison
from .spec import ACTIVE, CERTIFICATE, FAIL, INACTIVE, INSPECTION, INSTRUMENT, PASS, SPEC


OVERDUE = '已过期'
MISSING = '缺少证书'
DUE_TODAY = '当日到期'
DUE_SOON = '即将到期'
VALID = '有效'
STATUS_ORDER = (OVERDUE, MISSING, DUE_TODAY, DUE_SOON, VALID)

_FIELDS = {field['key']: field for field in SPEC['fields']}
_COLUMNS = (
    ('asset_id', '器具编号'), ('asset_name', '器具名称'), ('work_area', '作业区'),
    ('owner', '责任班组'), ('status', '证书状态'), ('certificate_id', '证书编号'),
    ('issued_on', '签发日'), ('expires_on', '到期日'), ('days_remaining', '剩余天数'),
    ('action', '班组处置'),
)


def _text(row, key):
    value = row.get(key)
    field = _FIELDS[key]
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= field['max_length']:
        raise ValueError(f'{field["label"]}须填写 1 至 {field["max_length"]} 个字符')
    return value.strip()


def _day(value, label):
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            pass
        else:
            if parsed.isoformat() == value:
                return parsed
    raise ValueError(f'{label}须为有效的 YYYY-MM-DD 日期')


def validate_rows(rows):
    instruments = {}
    certificates = defaultdict(dict)
    inspections = defaultdict(list)
    for index, row in enumerate(rows, start=2):
        try:
            asset_id = _text(row, 'asset_id')
            kind = row.get('record_type')
            if kind == INSTRUMENT:
                if asset_id in instruments:
                    raise ValueError(f'器具 {asset_id} 的台账重复')
                status = row.get('asset_status')
                if status not in (ACTIVE, INACTIVE):
                    raise ValueError('器具状态须为在用或停用')
                instruments[asset_id] = {
                    'asset_id': asset_id, 'asset_status': status,
                    **{key: _text(row, key) for key in ('asset_name', 'work_area', 'owner')},
                }
            elif kind == CERTIFICATE:
                code = _text(row, 'certificate_id')
                issued = _day(row.get('issued_on'), '签发日')
                expires = _day(row.get('expires_on'), '到期日')
                if expires < issued:
                    raise ValueError(f'证书 {code} 的到期日早于签发日')
                if code in certificates[asset_id]:
                    raise ValueError(f'器具 {asset_id} 的证书 {code} 重复')
                certificates[asset_id][code] = (issued, expires)
            elif kind == INSPECTION:
                shift = _day(row.get('shift'), '检查班次')
                # 旧版检查记录没有录入日期时视为当日录入（不算晚到）。
                recorded = _day(row.get('recorded_on'), '录入日期') if row.get('recorded_on') else shift
                result = row.get('inspection_result')
                if result not in (PASS, FAIL):
                    raise ValueError('检查结果须为合格或超差')
                if recorded < shift:
                    raise ValueError('检查记录的录入日期不能早于检查班次')
                if any(record['shift'] == shift for record in inspections[asset_id]):
                    raise ValueError(f'器具 {asset_id} 在 {shift} 已有检查记录')
                inspections[asset_id].append({'shift': shift, 'result': result, 'recorded_on': recorded})
            else:
                raise ValueError('记录类型须为器具台账、校准证书或检查记录')
        except ValueError as error:
            raise ValueError(f'CSV 第 {index} 行 · {error}') from None

    unknown = sorted((certificates.keys() | inspections.keys()) - instruments.keys())
    if unknown:
        raise ValueError(f'证书或检查记录缺少对应的器具台账，例如 {unknown[0]}')
    for records in inspections.values():
        records.sort(key=lambda record: record['shift'])
    return instruments, certificates, inspections


def _parameters(params):
    values = {}
    for field in SPEC['params']:
        key = field['key']
        value = params.get(key, field['default'])
        if field['type'] == 'date':
            value = _day(value, field['label'])
        elif type(value) is not int or not field['min'] <= value <= field['max']:
            raise ValueError(f'{field["label"]}须为 {field["min"]} 至 {field["max"]} 的整数')
        values[key] = value
    return values


def _asset_report(instrument, certificates, report_day, horizon):
    code = max(
        (code for code, (issued, _) in certificates.items() if issued <= report_day),
        key=lambda code: (certificates[code][0], code), default=None,
    )
    owner = instrument['owner']
    issued = expires = remaining = None
    if code is None:
        status = MISSING
        action = f'{owner}核对器具铭牌并向计量室补录证书。确认校准有效前暂停用于检验。'
    else:
        issued, expires = certificates[code]
        remaining = (expires - report_day).days
        if remaining < 0:
            status = OVERDUE
            action = f'{owner}停用并贴隔离标签，换用有效备用器具，登记送校。'
        elif remaining == 0:
            status = DUE_TODAY
            action = f'{owner}本班交接前安排换具和送校，次日启用前核对新证书。'
        elif remaining <= horizon:
            status = DUE_SOON
            action = f'{owner}在 {expires} 前预约送校并落实有效备用器具。'
        else:
            status = VALID
            action = f'{owner}继续使用，按台账日期复核校准计划。'

    return {
        **instrument, 'status': status, 'certificate_id': code,
        'issued_on': issued.isoformat() if issued else None,
        'expires_on': expires.isoformat() if expires else None,
        'days_remaining': remaining, 'action': action,
    }


def analyze(rows, params) -> dict:
    """对外结果：用于运行记录与 CSV 导出，不含逐班证据的原始映射。"""
    result, _ = analyze_full(rows, params)
    return result


def analyze_full(rows, params):
    """``(结果, 逐班证据)``。证据只用于按班次落库，不放进导出结果。"""
    options, snapshot, counts, total, covered, coverage = report_snapshot(rows, params)
    day = options['report_day']
    instruments, certificates, inspections = validate_rows(rows)
    compared, evidence = comparison.run(
        instruments, certificates, inspections, day,
        options['lead_days_a'], options['lead_days_b'])
    return _assemble(snapshot, compared, evidence, options, coverage, total, covered), evidence


def _assemble(snapshot, compared, evidence, options, coverage, total, covered):
    """把报告日快照与历史比较拼成运行结果，供首算和受影响班次重算共用。"""
    day = options['report_day']
    horizon = options['horizon_days']
    threshold = options['min_coverage_percent']
    counts = Counter(row['status'] for row in snapshot)
    ready = total > 0 and covered * 100 >= threshold * total
    if ready:
        headline = f'{day} 班报可分发 · {covered}/{total} 台有证书，{counts[OVERDUE]} 台已过期'
    elif total:
        headline = f'{day} 班报暂停分发 · 已覆盖 {covered}/{total} 台，低于 {threshold}% 门槛'
    else:
        headline = f'{day} 班报暂停分发 · 台账无在用器具'
    bounds = compared['bounds']

    return {
        'ready': ready,
        'headline': headline,
        'note': f'报告日 {day}，临期窗口 {horizon} 天。证书覆盖率 {coverage}，分发门槛 {threshold}%。'
                '已过期证书计入覆盖。同日签发按证书编号取字典序末位。'
                f'历史比较：方案 A 提前 {options["lead_days_a"]} 天、方案 B 提前 {options["lead_days_b"]} 天，'
                f'漏警台数之差 {bounds["lower"]:+d} 至 {bounds["upper"]:+d}（共 {bounds["counted"]} 台计入）。',
        'metrics': [
            {'label': '在用器具', 'value': total, 'detail': '按导入台账的在用状态统计'},
            {'label': '证书覆盖率', 'value': coverage, 'detail': f'{covered}/{total} 台 · 门槛 {threshold}%'},
            {'label': '已过期', 'value': counts[OVERDUE], 'detail': '立即停用并换具'},
            {'label': '临期（含当日）', 'value': counts[DUE_SOON] + counts[DUE_TODAY],
             'detail': f'其中 {counts[DUE_TODAY]} 台当日到期'},
            {'label': '缺少证书', 'value': counts[MISSING], 'detail': '截至报告日无已签发证书'},
            {'label': '漏警差（A−B）', 'value': f'{bounds["lower"]:+d} ~ {bounds["upper"]:+d}',
             'detail': f'{bounds["counted"]} 台计入差值，{len(compared["unsolved"])} 台单列'},
        ],
        'tables': [{
            'title': '在用器具证书与班组处置',
            'columns': [{'key': key, 'label': label} for key, label in _COLUMNS],
            'rows': snapshot,
        }] + _comparison_tables(compared, evidence),
        'charts': [{
            'title': '证书状态（器具数）', 'kind': 'bar',
            'series': [{'label': status, 'value': counts[status]} for status in STATUS_ORDER],
        }] if total else [],
        'sections': _comparison_sections(compared),
        'comparison': compared,
    }


def report_snapshot(rows, params):
    """只计算报告日快照，供受影响班次重算时复用。"""
    options = _parameters(params)
    day = options['report_day']
    horizon = options['horizon_days']
    instruments, certificates, inspections = validate_rows(rows)
    snapshot = [
        _asset_report(instrument, certificates.get(asset_id, {}), day, horizon)
        for asset_id, instrument in instruments.items() if instrument['asset_status'] == ACTIVE
    ]
    snapshot.sort(key=lambda row: (STATUS_ORDER.index(row['status']), row['days_remaining'] or 0, row['asset_id']))
    counts = Counter(row['status'] for row in snapshot)
    total = len(snapshot)
    covered = total - counts[MISSING]
    coverage = f'{covered / total:.2%}' if total else '待核实'
    return options, snapshot, counts, total, covered, coverage


def recompute(rows, params, published, evidence, affected):
    """补录后只重算受影响器具，其余沿用已发布汇总。

    ``published`` 为既有比较结果，``evidence`` 为 ``{asset_id: [逐班行]}``，
    ``affected`` 为数据发生变化、必须重算的器具编号。返回
    ``(结果, 新证据, 实际重算器具, 报告日)``；提前量改变时整批重算。
    """
    options, snapshot, _, total, covered, coverage = report_snapshot(rows, params)
    instruments, certificates, inspections = validate_rows(rows)
    day = options['report_day']
    lead_a = options['lead_days_a']
    lead_b = options['lead_days_b']

    if lead_a != published['lead_days']['a'] or lead_b != published['lead_days']['b']:
        # 提前量变了就是另一组方案，不能只补受影响器具，必须整批重算。
        summary, fresh = comparison.run(instruments, certificates, inspections, day, lead_a, lead_b)
        return (_assemble(snapshot, summary, fresh, options, coverage, total, covered),
                fresh, sorted(instruments), day)

    assets = {asset['asset_id']: asset for asset in published['assets']}
    unsolved = {asset['asset_id']: asset for asset in published['unsolved']}
    fresh = {key: list(value) for key, value in evidence.items()}
    rebuilt = []
    for asset_id in affected:
        instrument = instruments.get(asset_id)
        fresh.pop(asset_id, None)
        if instrument is None:
            assets.pop(asset_id, None)
            unsolved.pop(asset_id, None)
            rebuilt.append(asset_id)
            continue
        summary, rows_ = comparison.asset_summary(
            instrument, certificates.get(asset_id, {}), inspections.get(asset_id, []),
            day, lead_a, lead_b)
        if 'first_fail_shift' in summary:
            assets[asset_id] = summary
            unsolved.pop(asset_id, None)
            fresh[asset_id] = rows_
        else:
            unsolved[asset_id] = summary
            assets.pop(asset_id, None)
        rebuilt.append(asset_id)

    summary = comparison.aggregate(list(assets.values()), list(unsolved.values()), lead_a, lead_b)
    result = _assemble(snapshot, summary, fresh, options, coverage, total, covered)
    return result, fresh, rebuilt, day


def _comparison_sections(compared):
    bounds = compared['bounds']
    missed = compared['missed']
    return [{
        'title': '历史比较口径',
        'text': compared['note']
                + f'方案 A 漏警 {missed["a"]["min"]}–{missed["a"]["max"]} 台，'
                f'方案 B 漏警 {missed["b"]["min"]}–{missed["b"]["max"]} 台。'
                f'漏警台数差下界 {bounds["lower"]}、上界 {bounds["upper"]}。',
    }]


def _comparison_tables(compared, evidence):
    asset_rows = [{
        'asset_id': asset['asset_id'],
        'owner': asset['owner'],
        'window': f'{asset["window_from"]} ~ {asset["window_to"]}',
        'warning_a': asset['warning_a'] or '未预警',
        'warning_b': asset['warning_b'] or '未预警',
        'delta': f'{asset["delta"]["lower"]:+d} ~ {asset["delta"]["upper"]:+d}',
        'late': len(asset['late_records']),
    } for asset in compared['assets']]
    unsolved_rows = [{
        'asset_id': asset['asset_id'],
        'owner': asset['owner'],
        'reason': asset['reason'],
        'latest_shift': asset['latest_shift'],
        'latest_result': asset['latest_result'],
    } for asset in compared['unsolved']]

    timeline_rows = []
    for asset in compared['assets']:
        for row in evidence.get(asset['asset_id'], []):
            timeline_rows.append({
                'asset_id': asset['asset_id'],
                'shift': row['shift'],
                'certificate_id': row['certificate_id'],
                'expires_on': row['expires_on'],
                'days_remaining': row['days_remaining'],
                'scheme_a': '预警' if row['scheme_a'] else '—',
                'scheme_b': '预警' if row['scheme_b'] else '—',
                'inspection_result': row['inspection_result'],
                'recorded_on': row['recorded_on'],
                'late': '晚到' if row['late'] else '—',
            })

    tables = [{
        'title': '逐台漏警差值（两套方案共用同一组起点）',
        'columns': [
            {'key': 'asset_id', 'label': '器具编号'}, {'key': 'owner', 'label': '责任班组'},
            {'key': 'window', 'label': '可能起点区间'},
            {'key': 'warning_a', 'label': '方案 A 首次预警'}, {'key': 'warning_b', 'label': '方案 B 首次预警'},
            {'key': 'delta', 'label': '漏警差（A−B）'}, {'key': 'late', 'label': '晚到记录数'},
        ],
        'rows': asset_rows,
    }]
    if timeline_rows:
        tables.append({
            'title': '逐班还原的证据（当时证书、预警与检查依据）',
            'columns': [
                {'key': 'asset_id', 'label': '器具编号'}, {'key': 'shift', 'label': '班次'},
                {'key': 'certificate_id', 'label': '当班证书'}, {'key': 'expires_on', 'label': '到期日'},
                {'key': 'days_remaining', 'label': '剩余天数'},
                {'key': 'scheme_a', 'label': '方案 A'}, {'key': 'scheme_b', 'label': '方案 B'},
                {'key': 'inspection_result', 'label': '检查结果'},
                {'key': 'recorded_on', 'label': '录入日期'}, {'key': 'late', 'label': '是否晚到'},
            ],
            'rows': timeline_rows,
        })
    tables.append({
        'title': '未查出超差（单列，不计入差值）',
        'columns': [
            {'key': 'asset_id', 'label': '器具编号'}, {'key': 'owner', 'label': '责任班组'},
            {'key': 'reason', 'label': '原因'}, {'key': 'latest_shift', 'label': '最近检查班次'},
            {'key': 'latest_result', 'label': '最近结果'},
        ],
        'rows': unsolved_rows,
    })
    return tables
