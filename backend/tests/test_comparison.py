"""历史比较：同一组可能起点下两套提前量的漏警差值上下界。"""
from datetime import date, timedelta

from src.domain.comparison import (asset_summary, changed_assets, compare,
                                   first_warning, publish_gate, warning_at)
from src.domain import analysis

PASS, FAIL = '合格', '超差'
DAY = timedelta(days=1)
D = date.fromisoformat


def certs(**kwargs):
    return {code: (D(span[0]), D(span[1])) for code, span in kwargs.items()}


def records(*items):
    return [{'shift': D(shift), 'result': result, 'recorded_on': D(recorded)}
            for shift, result, recorded in items]


INSTRUMENT = {'asset_id': 'QC-X', 'asset_name': '卡尺', 'work_area': '机加工区',
              'owner': '车削一班', 'asset_status': '在用'}


def test_delta_sign_bounds():
    # 证书到期 11-20；A 提前 14 天 → 11-06 起预警；B 提前 30 天 → 10-21 起预警。
    cert = certs(CL=('2026-05-20', '2026-11-20'))
    # 上次合格 11-05，首次超差 11-18，可能起点 11-06 ~ 11-18。
    summary, rows = asset_summary(
        INSTRUMENT, cert, records(('2026-11-05', PASS, '2026-11-05'),
                                  ('2026-11-18', FAIL, '2026-11-20')),
        D('2026-11-21'), 14, 30)
    # 起点 11-06：A 的预警恰在起点当日（不算早于起点）→ A 漏警，B 已在 10-21 预警 → 差 +1。
    # 起点 11-07：两者预警都早于起点 → 差 0。故单台差区间 [0, 1]。
    assert summary['delta'] == {'lower': 0, 'upper': 1}, summary['delta']
    # 只有一行逐班证据覆盖整个窗口。
    assert rows[0]['shift'] == '2026-11-06' and rows[-1]['shift'] == '2026-11-18'


def test_late_record_does_not_change_warning():
    # 晚到记录把超差补在 11-18、11-20 录用；预警仍只看证书签发日。
    cert = certs(CL=('2026-05-20', '2026-11-20'))
    active = [(D('2026-05-20'), 'CL', D('2026-11-20'))]
    summary, rows = asset_summary(
        INSTRUMENT, cert, records(('2026-10-01', PASS, '2026-10-01'),
                                  ('2026-11-18', FAIL, '2026-11-20')),
        D('2026-11-21'), 14, 30)
    # 晚到记录落在窗口末班，记为晚到，但不改变起点或预警。
    assert summary['late_records'][0]['shift'] == '2026-11-18'
    assert summary['late_records'][0]['recorded_on'] == '2026-11-20'
    assert rows[-1]['late'] is True


def test_future_certificate_not_backfilled():
    # 11-22 才签发的证书不能进入 11-21 报告日的逐班还原。
    cert = certs(OLD=('2026-05-20', '2026-11-20'), NEW=('2026-11-22', '2027-05-22'))
    records_ = records(('2026-11-18', FAIL, '2026-11-18'))
    summary, rows = asset_summary(INSTRUMENT, cert, records_, D('2026-11-21'), 14, 30)
    assert all(row['certificate_id'] in (None, 'OLD') for row in rows)
    # 预警必须来自旧证（到期 11-20），与 A=14 天一致。
    assert summary['warning_a'] == '2026-11-06'


def test_unsolved_listed_separately():
    cert = certs(CL=('2026-05-20', '2026-11-20'))
    summary, rows = asset_summary(
        INSTRUMENT, cert, records(('2026-11-01', PASS, '2026-11-01')), D('2026-11-21'), 14, 30)
    assert 'first_fail_shift' not in summary
    assert summary['reason'] == '仅有合格记录，未查出超差'
    assert rows == []


def test_no_certificate_means_missed():
    summary, _ = asset_summary(
        INSTRUMENT, {}, records(('2026-11-10', FAIL, '2026-11-10')), D('2026-11-21'), 14, 30)
    assert summary['warning_a'] is None
    assert summary['missed_a'] == {'min': 1, 'max': 1}


def test_compare_aggregates_bounds_and_counted():
    instruments = {
        'QC-1': {**INSTRUMENT, 'asset_id': 'QC-1'},
        'QC-2': {**INSTRUMENT, 'asset_id': 'QC-2'},
        'QC-3': {**INSTRUMENT, 'asset_id': 'QC-3'},
    }
    certificates = {
        'QC-1': certs(CL=('2026-05-20', '2026-11-20')),
        'QC-2': certs(CL=('2026-05-20', '2026-11-20')),
        'QC-3': certs(CL=('2026-05-20', '2026-11-20')),
    }
    inspections = {
        'QC-1': records(('2026-11-05', PASS, '2026-11-05'), ('2026-11-18', FAIL, '2026-11-18')),
        'QC-2': records(('2026-11-05', PASS, '2026-11-05'), ('2026-11-18', FAIL, '2026-11-18')),
        'QC-3': records(('2026-11-01', PASS, '2026-11-01')),
    }
    result, _ = compare(instruments, certificates, inspections, D('2026-11-21'), 14, 30)
    assert result['bounds']['counted'] == 2
    assert len(result['unsolved']) == 1
    assert result['bounds']['lower'] <= result['bounds']['upper']


def test_changed_assets_detects_new_record():
    base = ({'QC-1': INSTRUMENT}, {'QC-1': certs(CL=('2026-05-20', '2026-11-20'))},
            {'QC-1': records(('2026-11-01', PASS, '2026-11-01'))})
    new = (base[0], base[1],
           {'QC-1': records(('2026-11-01', PASS, '2026-11-01'),
                            ('2026-11-18', FAIL, '2026-11-20'))})
    assert changed_assets(base, new) == ['QC-1']
    assert changed_assets(base, base) == []


def test_publish_gate_stale_rules():
    assert publish_gate(None, None, 5, None) == (True, 'first')
    assert publish_gate(7, 3, 5, 3) == (False, 'stale_revision')
    assert publish_gate(7, 3, 7, 2) == (False, 'stale_version')
    assert publish_gate(7, 3, 7, None) == (False, 'stale_version')
    assert publish_gate(7, 3, 7, 3) == (True, 'publish')
    assert publish_gate(7, 3, 9, 3) == (True, 'publish')


def test_same_day_certificate_takes_last_code():
    # 同日两张证书取编号字典序末位（CL-2 > CL-1）。
    cert = {'CL-1': (D('2026-05-20'), D('2026-11-20')),
            'CL-2': (D('2026-05-20'), D('2026-12-31'))}
    instruments = {'QC-1': {**INSTRUMENT, 'asset_id': 'QC-1'}}
    inspections = {'QC-1': records(('2026-11-10', FAIL, '2026-11-10'))}
    summary, _ = asset_summary(instruments['QC-1'], cert, inspections['QC-1'],
                               D('2026-11-21'), 14, 30)
    # 有效证书是 CL-2，到期 12-31，A=14 天时预警在 12-17，晚于报告日 → 无预警。
    assert summary['warning_a'] is None


def _rows(**overrides):
    base = dict(record_type=None, asset_id=None, asset_name='卡尺', work_area='机加工区',
                owner='车削一班', asset_status=None, certificate_id=None, issued_on=None,
                expires_on=None, shift=None, inspection_result=None, recorded_on=None)
    base.update(overrides)
    return base


def test_recompute_only_touches_affected_asset():
    rows = [
        _rows(record_type='器具台账', asset_id='QC-1', asset_status='在用'),
        _rows(record_type='器具台账', asset_id='QC-2', asset_status='在用'),
        _rows(record_type='校准证书', asset_id='QC-1', certificate_id='CL-1',
              issued_on='2026-05-20', expires_on='2026-11-20'),
        _rows(record_type='校准证书', asset_id='QC-2', certificate_id='CL-2',
              issued_on='2026-05-20', expires_on='2026-11-20'),
        _rows(record_type='检查记录', asset_id='QC-1', shift='2026-11-05',
              inspection_result='合格', recorded_on='2026-11-05'),
        _rows(record_type='检查记录', asset_id='QC-1', shift='2026-11-18',
              inspection_result='超差', recorded_on='2026-11-18'),
        _rows(record_type='检查记录', asset_id='QC-2', shift='2026-11-10',
              inspection_result='合格', recorded_on='2026-11-10'),
    ]
    params = {'report_day': '2026-11-21', 'horizon_days': 14, 'min_coverage_percent': 80,
              'lead_days_a': 14, 'lead_days_b': 30}
    published, published_evidence = analysis.analyze_full(rows, params)
    assert [a['asset_id'] for a in published['comparison']['unsolved']] == ['QC-2']

    # 晚到的 QC-2 超差补录（11-20 检查、11-22 录用）进入新批次。
    backfill = rows + [_rows(record_type='检查记录', asset_id='QC-2', shift='2026-11-20',
                             inspection_result='超差', recorded_on='2026-11-22')]
    parsed_old = analysis.validate_rows(rows)
    parsed_new = analysis.validate_rows(backfill)
    changed = changed_assets(parsed_old, parsed_new)
    assert changed == ['QC-2']

    result, evidence, rebuilt, _ = analysis.recompute(
        backfill, params, published['comparison'], published_evidence, changed)
    # 只有 QC-2 被重算，QC-1 的汇总原样保留。
    assert rebuilt == ['QC-2']
    assert 'QC-2' not in [a['asset_id'] for a in result['comparison']['unsolved']]
    assert evidence['QC-2'][-1]['late'] is True


if __name__ == '__main__':
    tests = [value for name, value in sorted(globals().items()) if name.startswith('test_')]
    for test in tests:
        test()
        print('ok', test.__name__)
    print(f'{len(tests)} tests passed')
