"""澄岭精密的固定演练台账、证书历史与历史检查记录。"""

from .spec import ACTIVE, CERTIFICATE, DEMO_DAY, FAIL, INACTIVE, INSPECTION, INSTRUMENT, PASS


def demo_rows() -> list[dict]:
    instruments = [
        ('QC-101', '数显卡尺', '机加工区', '车削一班', ACTIVE),
        ('QC-102', '扭矩扳手', '装配区', '装配二班', ACTIVE),
        ('QC-103', '外径千分尺', '机加工区', '磨削班', ACTIVE),
        ('QC-104', '针规组', '终检区', '终检班', ACTIVE),
        ('QC-105', '电子天平', '终检区', '来料检验班', ACTIVE),
        ('QC-106', '高度规', '终检区', '终检班', ACTIVE),
        ('QC-107', '指针式压力表', '装配区', '装配二班', INACTIVE),
    ]
    certificates = [
        ('QC-103', 'CL-103-26', '2026-06-05', '2026-12-05'),
        ('QC-101', 'CL-101-27', '2026-11-22', '2027-05-22'),
        ('QC-105', 'CL-105-26', DEMO_DAY, '2027-05-21'),
        ('QC-101', 'CL-101-26', '2026-05-20', '2026-11-20'),
        ('QC-101', 'CL-101-25', '2025-11-20', '2026-05-20'),
        ('QC-102', 'CL-102-26', '2026-05-21', DEMO_DAY),
        ('QC-104', 'CL-104-26', '2026-06-06', '2026-12-06'),
        ('QC-106', 'CL-106-26', '2026-11-22', '2027-05-22'),
        ('QC-107', 'CL-107-25', '2025-11-05', '2026-05-05'),
    ]
    # (器具, 检查班次, 结果, 录入日期)。录入日期晚于班次即晚到记录，只补实绩。
    inspections = [
        ('QC-101', '2026-10-30', PASS, '2026-10-30'),
        ('QC-101', '2026-11-10', PASS, '2026-11-10'),
        ('QC-101', '2026-11-18', FAIL, '2026-11-20'),
        ('QC-102', '2026-11-05', PASS, '2026-11-05'),
        ('QC-102', '2026-11-20', FAIL, '2026-11-22'),
        ('QC-103', '2026-09-20', PASS, '2026-09-20'),
        ('QC-103', '2026-11-19', FAIL, '2026-11-21'),
        ('QC-104', '2026-11-01', PASS, '2026-11-01'),
        ('QC-106', '2026-11-15', PASS, '2026-11-15'),
        ('QC-106', '2026-11-16', FAIL, '2026-11-19'),
    ]

    rows = [
        dict(record_type=INSTRUMENT, asset_id=asset_id, asset_name=name, work_area=area,
             owner=owner, asset_status=status, certificate_id=None, issued_on=None, expires_on=None,
             shift=None, inspection_result=None, recorded_on=None)
        for asset_id, name, area, owner, status in instruments
    ]
    rows += [
        dict(record_type=CERTIFICATE, asset_id=asset_id, asset_name=None, work_area=None,
             owner=None, asset_status=None, certificate_id=code, issued_on=issued, expires_on=expires,
             shift=None, inspection_result=None, recorded_on=None)
        for asset_id, code, issued, expires in certificates
    ]
    rows += [
        dict(record_type=INSPECTION, asset_id=asset_id, asset_name=None, work_area=None,
             owner=None, asset_status=None, certificate_id=None, issued_on=None, expires_on=None,
             shift=shift, inspection_result=result, recorded_on=recorded)
        for asset_id, shift, result, recorded in inspections
    ]
    return rows
