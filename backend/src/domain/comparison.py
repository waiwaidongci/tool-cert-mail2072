"""逐班还原证书历史，比较两套送校提前量的漏警台数上下界。

口径（沿用到期清单的证书选取规则，并补充历史检查口径）：

- 逐班还原：某个班次只承认“签发日不晚于该班次”的最新证书；同一签发日按证书
  编号字典序取最后一条。于是后续才签发的证书不会倒灌进历史班报。
- 晚到记录：检查记录带独立的录入日期 ``recorded_on``。晚到记录（录入日晚于检查
  班次）只用于补实绩；预警完全由证书签发日推导，不看录入时间，所以不会改写当
  班预警。
- 预警：当班有效证书的剩余天数不超过该方案的送校提前量（含当日到期与已过期）。
  没有证书时不存在到期预警。
- 可能起点：每台器具取首次超差班次 ``F`` 与之前最近一次合格班次 ``L``，可能起点
  为 ``L`` 之后到 ``F``（含）的每个班次。此前没有合格记录时，自最早一条检查班次
  起算。
- 漏警：起点之前（严格早于起点）没有预警。两台方案的起点取同一组值。
- 未查出超差：没有任何超差检查记录的器具单独列出，不参与差值。

差值上下界：每台器具的可能起点互不牵连，``漏警A - 漏警B`` 的总差值区间等于
逐台区间之和（``lower = Σ 单台最小差值``，``upper = Σ 单台最大差值``）。
"""

from datetime import timedelta

from .spec import ACTIVE, FAIL, PASS

DAY = timedelta(days=1)
# 证据表按班逐日展开，限定最长跨度，避免异常数据把历史拉得过长。
MAX_EVIDENCE_DAYS = 366


def active_certificates(certificates):
    """按签发日还原证书段，返回 ``[(issued, code, expires)]``（升序）。

    同一签发日只保留编号字典序末位的证书，与到期清单的选取规则一致。
    """
    latest = {}
    for code, (issued, expires) in certificates.items():
        current = latest.get(issued)
        if current is None or code > current[0]:
            latest[issued] = (code, expires)
    return [(issued, code, expires) for issued, (code, expires) in sorted(latest.items())]


def certificate_at(active, day):
    """返回 ``day`` 当班已收到的最新证书 ``(code, issued, expires)``，没有则 ``None``。"""
    found = None
    for issued, code, expires in active:
        if issued > day:
            break
        found = (code, issued, expires)
    return found


def warning_at(active, horizon, day):
    """返回 ``(是否预警, 证书, 剩余天数)``；无证书时全部为 ``None``。"""
    found = certificate_at(active, day)
    if found is None:
        return None, None, None
    code, issued, expires = found
    remaining = (expires - day).days
    return remaining <= horizon, found, remaining


def first_warning(active, horizon, from_day, report_day):
    """``from_day``（含）之后最早的到期预警班次，没有则 ``None``。

    某张证书的预警自 ``max(签发日, 到期日 - 提前量)`` 起，持续到被下一张证书替
    换前一个班次。``from_day`` 为空表示不设下限。
    """
    best = None
    for index, (issued, code, expires) in enumerate(active):
        if issued > report_day:
            break
        next_issue = active[index + 1][0] if index + 1 < len(active) else None
        segment_end = report_day if next_issue is None else min(report_day, next_issue - DAY)
        start = max(issued, expires - timedelta(days=horizon))
        if from_day is not None:
            start = max(start, from_day)
        if start <= segment_end and (best is None or start < best):
            best = start
    return best


def _missed(warning, day):
    """起点为 ``day`` 时是否漏警：预警必须严格早于起点。"""
    return warning is None or warning >= day


def _shift_span(window_from, window_to):
    """可能起点窗口内的候选班次（``window_from`` 到 ``window_to``，含两端）。"""
    days = []
    day = window_from
    while day <= window_to:
        days.append(day)
        day += DAY
    return days


def _delta(warning_a, warning_b, spans):
    """单台器具在候选起点上的 ``漏警A - 漏警B`` 最小值与最大值。"""
    diffs = [int(_missed(warning_a, day)) - int(_missed(warning_b, day)) for day in spans]
    return min(diffs), max(diffs)


def _missed_bounds(warning, spans):
    """单台器具漏警台数（0/1）的可达最小、最大值。"""
    values = [int(_missed(warning, day)) for day in spans]
    return min(values), max(values)


def timeline(active, records, window_from, window_to, report_day, horizon_a, horizon_b,
             warning_a, warning_b):
    """可能起点窗口内逐班还原的预警与检查依据（每班一条）。"""
    by_shift = {record['shift']: record for record in records}
    end = min(window_to, report_day)
    rows = []
    for day in _shift_span(window_from, end):
        fired_a, certificate, remaining = warning_at(active, horizon_a, day)
        fired_b = warning_at(active, horizon_b, day)[0]
        inspection = by_shift.get(day)
        rows.append({
            'shift': day.isoformat(),
            'certificate_id': certificate[0] if certificate else None,
            'issued_on': certificate[1].isoformat() if certificate else None,
            'expires_on': certificate[2].isoformat() if certificate else None,
            'days_remaining': remaining,
            'scheme_a': bool(fired_a),
            'scheme_b': bool(fired_b),
            'inspection_result': inspection['result'] if inspection else None,
            'recorded_on': inspection['recorded_on'].isoformat() if inspection else None,
            'late': bool(inspection and inspection['recorded_on'] > inspection['shift']),
            'caught_a': bool(warning_a is not None and warning_a < day),
            'caught_b': bool(warning_b is not None and warning_b < day),
        })
    return rows


def _unsolved(instrument, records):
    if not records:
        reason = '无检查记录'
    elif all(record['result'] == PASS for record in records):
        reason = '仅有合格记录，未查出超差'
    else:
        reason = '未查出超差'
    latest = records[-1] if records else None
    return {
        'asset_id': instrument['asset_id'],
        'asset_name': instrument['asset_name'],
        'work_area': instrument['work_area'],
        'owner': instrument['owner'],
        'asset_status': instrument['asset_status'],
        'inspection_count': len(records),
        'latest_shift': latest['shift'].isoformat() if latest else None,
        'latest_result': latest['result'] if latest else None,
        'reason': reason,
    }


def asset_summary(instrument, certificates, records, report_day, lead_a, lead_b):
    """单台器具的历史比较汇总。

    返回 ``(summary, evidence_rows)``：查出超差时 ``summary`` 带 ``first_fail_shift``
    与差值区间，否则为“未查出超差”条目。未到报告日的记录不参与。
    """
    records = sorted((record for record in records if record['shift'] <= report_day),
                     key=lambda record: record['shift'])
    fail_index = next((index for index, record in enumerate(records) if record['result'] == FAIL), None)
    if fail_index is None:
        return _unsolved(instrument, records), []

    first_fail = records[fail_index]['shift']
    passes = [record['shift'] for record in records[:fail_index] if record['result'] == PASS]
    last_pass = passes[-1] if passes else None
    window_from = last_pass + DAY if last_pass is not None else records[0]['shift']
    window_to = first_fail
    spans = _shift_span(window_from, window_to)
    if len(spans) > MAX_EVIDENCE_DAYS:
        # 可能起点过长时只保留靠近首次超差的一段，避免逐班证据爆炸。
        spans = spans[-MAX_EVIDENCE_DAYS:]
        window_from = spans[0]

    active = [segment for segment in active_certificates(certificates) if segment[0] <= report_day]
    warning_a = first_warning(active, lead_a, last_pass, report_day)
    warning_b = first_warning(active, lead_b, last_pass, report_day)
    delta_low, delta_high = _delta(warning_a, warning_b, spans)
    a_low, a_high = _missed_bounds(warning_a, spans)
    b_low, b_high = _missed_bounds(warning_b, spans)

    late_records = [
        {'shift': record['shift'].isoformat(), 'recorded_on': record['recorded_on'].isoformat(),
         'result': record['result']}
        for record in records if record['recorded_on'] > record['shift']
    ]
    summary = {
        'asset_id': instrument['asset_id'],
        'asset_name': instrument['asset_name'],
        'work_area': instrument['work_area'],
        'owner': instrument['owner'],
        'asset_status': instrument['asset_status'],
        'last_pass_shift': last_pass.isoformat() if last_pass else None,
        'first_fail_shift': first_fail.isoformat(),
        'window_from': window_from.isoformat(),
        'window_to': window_to.isoformat(),
        'warning_a': warning_a.isoformat() if warning_a else None,
        'warning_b': warning_b.isoformat() if warning_b else None,
        'delta': {'lower': delta_low, 'upper': delta_high},
        'missed_a': {'min': a_low, 'max': a_high},
        'missed_b': {'min': b_low, 'max': b_high},
        'late_records': late_records,
    }
    evidence = timeline(active, records, window_from, window_to, report_day,
                        lead_a, lead_b, warning_a, warning_b)
    return summary, evidence


def _asset_relevant(instrument, records):
    """是否纳入历史比较：在用器具，或留有检查记录（含已停用）的器具。"""
    return instrument['asset_status'] == ACTIVE or bool(records)


def aggregate(assets, unsolved, lead_a, lead_b):
    """把逐台汇总累加成上下界与说明。"""
    lower = sum(asset['delta']['lower'] for asset in assets)
    upper = sum(asset['delta']['upper'] for asset in assets)
    missed_a_low = sum(asset['missed_a']['min'] for asset in assets)
    missed_a_high = sum(asset['missed_a']['max'] for asset in assets)
    missed_b_low = sum(asset['missed_b']['min'] for asset in assets)
    missed_b_high = sum(asset['missed_b']['max'] for asset in assets)
    counted = len(assets)
    return {
        'lead_days': {'a': lead_a, 'b': lead_b},
        'bounds': {'lower': lower, 'upper': upper, 'counted': counted},
        'missed': {
            'a': {'min': missed_a_low, 'max': missed_a_high},
            'b': {'min': missed_b_low, 'max': missed_b_high},
        },
        'assets': sorted(assets, key=lambda asset: asset['asset_id']),
        'unsolved': sorted(unsolved, key=lambda asset: asset['asset_id']),
        'note': (
            f'在 {counted} 台查出超差的器具上，两套方案使用同一组可能起点时，'
            f'方案 A 减方案 B 的漏警台数之差落在 [{lower}, {upper}]。'
            f'方案 A 漏警 {missed_a_low} 至 {missed_a_high} 台，'
            f'方案 B 漏警 {missed_b_low} 至 {missed_b_high} 台。'
            '晚到检查记录只补实绩、不改当班预警；未查出超差的器具单列，未计入上下界。'
        ),
    }


def compare(instruments, certificates, inspections, report_day, lead_a, lead_b):
    """对全部器具做历史比较，返回 (汇总, 逐台证据)。"""
    return run(instruments, certificates, inspections, report_day, lead_a, lead_b)


def run(instruments, certificates, inspections, report_day, lead_a, lead_b):
    """``compare`` 的完整形式，返回 ``(aggregate, evidence)``。

    ``evidence`` 为 ``{asset_id: [逐班行, ...]}``，按班次落库时据此拆分。
    """
    assets = []
    unsolved = []
    evidence = {}
    for asset_id in sorted(instruments):
        instrument = instruments[asset_id]
        records = inspections.get(asset_id, [])
        if not _asset_relevant(instrument, records):
            continue
        summary, rows = asset_summary(instrument, certificates.get(asset_id, {}), records,
                                      report_day, lead_a, lead_b)
        if 'first_fail_shift' in summary:
            assets.append(summary)
            evidence[asset_id] = rows
        else:
            unsolved.append(summary)
    return aggregate(assets, unsolved, lead_a, lead_b), evidence


def changed_assets(old, new):
    """两次解析结果之间数据发生变化的器具编号（升序）。

    ``old``/``new`` 为 ``(instruments, certificates, inspections)``。任何台账、证书
    或检查记录的差异都会把该器具标为受影响，避免用旧汇总冒充新结果。
    """
    old_instruments, old_certificates, old_inspections = old
    new_instruments, new_certificates, new_inspections = new
    assets = sorted(
        set(old_instruments) | set(new_instruments)
        | set(old_certificates) | set(new_certificates)
        | set(old_inspections) | set(new_inspections)
    )
    changed = []
    for asset in assets:
        if old_instruments.get(asset) != new_instruments.get(asset):
            changed.append(asset)
        elif old_certificates.get(asset) != new_certificates.get(asset):
            changed.append(asset)
        elif _normalized(old_inspections.get(asset, [])) != _normalized(new_inspections.get(asset, [])):
            changed.append(asset)
    return changed


def _normalized(records):
    return [
        (record['shift'].isoformat(), record['result'], record['recorded_on'].isoformat())
        for record in sorted(records, key=lambda record: record['shift'])
    ]


def dump_parsed(instruments, certificates, inspections):
    """把解析结果序列化为可入库的 JSON（日期转 ISO 字符串）。"""
    return {
        'instruments': {asset: dict(instruments[asset]) for asset in sorted(instruments)},
        'certificates': {
            asset: {code: [issued.isoformat(), expires.isoformat()]
                    for code, (issued, expires) in sorted(certificates.get(asset, {}).items())}
            for asset in sorted(certificates)},
        'inspections': {
            asset: [{'shift': record['shift'].isoformat(), 'result': record['result'],
                     'recorded_on': record['recorded_on'].isoformat()}
                    for record in sorted(records, key=lambda record: record['shift'])]
            for asset, records in sorted(inspections.items())},
    }


def load_parsed(payload):
    """``dump_parsed`` 的逆操作，返回解析元组。"""
    from datetime import date
    instruments = {asset: dict(fields) for asset, fields in payload.get('instruments', {}).items()}
    certificates = {
        asset: {code: (date.fromisoformat(span[0]), date.fromisoformat(span[1]))
                for code, span in codes.items()}
        for asset, codes in payload.get('certificates', {}).items()}
    inspections = {
        asset: [{'shift': date.fromisoformat(record['shift']), 'result': record['result'],
                 'recorded_on': date.fromisoformat(record['recorded_on'])}
                for record in records]
        for asset, records in payload.get('inspections', {}).items()}
    return instruments, certificates, inspections


def publish_gate(stored_revision, stored_version, job_revision, base_version):
    """判断本次发布能否落库，返回 ``(是否允许, 原因)``。

    - 尚无已发布结果：首次发布直接通过。
    - 任务所用数据批次早于已发布批次：拒绝（旧任务不能覆盖新结果）。
    - 批次相同但任务基于的版本与当前已发布版本不同：拒绝。这样补录与重算并发
      时，先到的任务发布，后到的旧基础任务被丢弃，不会覆盖新结果。
    """
    if stored_revision is None:
        return True, 'first'
    if job_revision < stored_revision:
        return False, 'stale_revision'
    if job_revision == stored_revision and base_version != stored_version:
        return False, 'stale_version'
    return True, 'publish'
