"""历史比较任务的排队、受影响班次重算与版本化发布。"""

import logging
from datetime import timedelta

from sqlalchemy import or_, select

from src.config.database import Session
from src.constants.enums import Status
from src.domain import analysis, comparison
from src.domain.comparison import publish_gate
from src.models.comparison import Comparison, ComparisonJob, ComparisonShift
from src.models.source import Dataset
from src.services.audit import record
from src.utils.time import now

log = logging.getLogger(__name__)


def scope_of(dataset_name, params):
    """比较身份：同一批次名、报告日与两套提前量。补录沿用同一身份原地更新。"""
    return '|'.join((
        dataset_name,
        str(params['report_day']),
        f"A{params['lead_days_a']}",
        f"B{params['lead_days_b']}",
    ))


def enqueue(db, dataset, name, params, actor, base_version=None):
    """把一次历史比较登记为后台任务。"""
    job = ComparisonJob(dataset_id=dataset.id, dataset_name=dataset.name, name=name,
                        params=dict(params), actor=actor, base_version=base_version)
    db.add(job)
    db.flush()
    record(db, actor, 'comparison.queued', job.id, dataset_id=dataset.id)
    return job


def claim():
    """领取一个待执行的比较任务，带租约，便于中断后重试。"""
    stamp = now()
    with Session.begin() as db:
        query = select(ComparisonJob).where(
            or_(ComparisonJob.status == Status.QUEUED,
                (ComparisonJob.status == Status.RUNNING) & (ComparisonJob.lease_until < stamp)))
        job = db.scalar(query.order_by(ComparisonJob.id).limit(1).with_for_update(skip_locked=True))
        if job is None:
            return None
        if job.attempt >= 3:
            job.status = Status.FAILED
            job.error = '后台进程多次中断，请重新发起比较'
            job.finished_at = stamp
            record(db, 'worker', 'comparison.failed', job.id, reason=job.error)
            return None
        job.status = Status.RUNNING
        job.attempt += 1
        job.lease_until = stamp + timedelta(minutes=3)
        return job.id, job.attempt


def _load_evidence(db, comparison_id):
    evidence = {}
    for row in db.scalars(select(ComparisonShift).where(ComparisonShift.comparison_id == comparison_id)):
        evidence.setdefault(row.asset_id, []).append(row.payload)
    for rows in evidence.values():
        rows.sort(key=lambda item: item['shift'])
    return evidence


def _write_evidence(db, comparison_id, fresh):
    """只改写内容变化的 (器具, 班次) 证据行，其余保留。"""
    current = {(row.asset_id, row.shift): row
               for row in db.scalars(select(ComparisonShift)
                                     .where(ComparisonShift.comparison_id == comparison_id))}
    rewritten = []
    for asset_id, rows in fresh.items():
        for payload in rows:
            key = (asset_id, payload['shift'])
            existing = current.pop(key, None)
            if existing is None:
                db.add(ComparisonShift(comparison_id=comparison_id, asset_id=asset_id,
                                       shift=payload['shift'], payload=payload))
                rewritten.append(payload['shift'])
            elif existing.payload != payload:
                existing.payload = payload
                existing.updated_at = now()
                rewritten.append(payload['shift'])
    for row in current.values():
        db.delete(row)
        rewritten.append(row.shift)
    return sorted(set(rewritten))


def _publish(db, job, parsed, result, evidence, mode):
    params = job.params
    scope = scope_of(job.dataset_name, params)
    stored = db.scalar(select(Comparison).where(Comparison.scope == scope).with_for_update())
    revision = job.dataset_id
    allowed, reason = publish_gate(
        stored.revision if stored else None,
        stored.version if stored else None,
        revision, job.base_version)
    if not allowed:
        job.status = Status.FAILED
        job.error = '结果基于较旧的数据批次，已被较新的发布取代'
        job.finished_at = now()
        record(db, 'worker', 'comparison.rejected', job.id, reason=reason,
               scope=scope, revision=revision)
        return False

    if stored is None:
        stored = Comparison(scope=scope, dataset_name=job.dataset_name, params=dict(params),
                            report_day=params['report_day'],
                            lead_days_a=params['lead_days_a'], lead_days_b=params['lead_days_b'],
                            dataset_id=job.dataset_id, revision=revision, version=0,
                            author=job.actor)
        db.add(stored)
        db.flush()
    stored.params = dict(params)
    stored.dataset_id = job.dataset_id
    stored.revision = revision
    stored.version += 1
    stored.result = {key: value for key, value in result.items() if key != 'evidence'}
    stored.source = comparison.dump_parsed(*parsed)
    stored.published_at = now()

    rewritten = _write_evidence(db, stored.id, evidence)
    job.status = Status.COMPLETE
    job.comparison_id = stored.id
    job.finished_at = now()
    job.error = None
    record(db, 'worker', 'comparison.published', job.id, scope=scope, version=stored.version,
           revision=revision, mode=mode, shifts=len(rewritten))
    return True


def execute(job_id, attempt):
    """执行比较任务：新批次只重算受影响器具，其余沿用已发布汇总。"""
    with Session.begin() as db:
        job = db.get(ComparisonJob, job_id, with_for_update=True)
        if job is None or job.attempt != attempt or job.status != Status.RUNNING:
            return
        dataset = db.get(Dataset, job.dataset_id)
        try:
            parsed = analysis.validate_rows(dataset.rows)
        except ValueError as error:
            job.status = Status.FAILED
            job.error = str(error)[:500]
            job.finished_at = now()
            record(db, 'worker', 'comparison.failed', job.id, reason=job.error)
            return

        scope = scope_of(job.dataset_name, job.params)
        stored = db.scalar(select(Comparison).where(Comparison.scope == scope).with_for_update())
        prior_source = comparison.load_parsed(stored.source) if stored and stored.source else None
        prior_result = (stored.result or {}).get('comparison') if stored else None
        prior_evidence = _load_evidence(db, stored.id) if stored else {}

        if prior_result and prior_source and job.dataset_id > stored.revision:
            changed = comparison.changed_assets(prior_source, parsed)
            result, evidence, rebuilt, _ = analysis.recompute(
                dataset.rows, job.params, prior_result, prior_evidence, changed)
            mode = 'partial' if changed else 'unchanged'
        else:
            result, evidence = analysis.analyze_full(dataset.rows, job.params)
            rebuilt = sorted(parsed[0])
            mode = 'full'

        job.recomputed = rebuilt
        _publish(db, job, parsed, result, evidence, mode)
