from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.config.database import connection
from src.constants.enums import Role
from src.controllers.auth import allow, current
from src.models.comparison import Comparison, ComparisonJob, ComparisonShift
from src.models.identity import User
from src.models.source import Dataset
from src.schemas.requests import ComparisonRequest
from src.services.comparisons import enqueue, scope_of
from src.services.validation import normalize_params
from src.utils import views
from src.utils.wakeup import wake

router = APIRouter(prefix='/comparisons')


def _dataset(db, body):
    item = db.get(Dataset, body.dataset_id)
    if not item:
        raise HTTPException(404, '找不到指定的数据批次')
    if item.name != body.dataset_name:
        raise HTTPException(409, '数据批次名称与批次不符，请重新选择')
    return item


@router.get('')
def index(db: Session = Depends(connection), actor: User = Depends(current)):
    return [views.comparison(item) for item in db.scalars(select(Comparison).order_by(Comparison.id.desc()).limit(100))]


@router.get('/jobs')
def jobs(db: Session = Depends(connection), actor: User = Depends(current)):
    return [views.comparison_job(item) for item in db.scalars(select(ComparisonJob).order_by(ComparisonJob.id.desc()).limit(100))]


@router.get('/{comparison_id}')
def detail(comparison_id: int, db: Session = Depends(connection), actor: User = Depends(current)):
    item = db.get(Comparison, comparison_id)
    if not item:
        raise HTTPException(404, '找不到该比较结果')
    return views.comparison(item, detail=True)


@router.get('/{comparison_id}/shifts')
def shifts(comparison_id: int, asset: str | None = None,
           db: Session = Depends(connection), actor: User = Depends(current)):
    if not db.get(Comparison, comparison_id):
        raise HTTPException(404, '找不到该比较结果')
    query = select(ComparisonShift).where(ComparisonShift.comparison_id == comparison_id)
    if asset:
        query = query.where(ComparisonShift.asset_id == asset)
    rows = db.scalars(query.order_by(ComparisonShift.asset_id, ComparisonShift.shift))
    return [{'asset_id': row.asset_id, **row.payload} for row in rows]


@router.post('', status_code=202)
def create(body: ComparisonRequest, db: Session = Depends(connection),
           actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    item = _dataset(db, body)
    params = normalize_params(body.params)
    stored = db.scalar(select(Comparison).where(Comparison.scope == scope_of(item.name, params)))
    job = enqueue(db, item, body.name, params, actor.username,
                  base_version=stored.version if stored else None)
    db.commit()
    wake()
    return views.comparison_job(job)


@router.post('/{comparison_id}/backfill', status_code=202)
def backfill(comparison_id: int, db: Session = Depends(connection),
             actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    """补录后按受影响班次重算：沿用已发布比较，读取最新数据批次。"""
    item = db.get(Comparison, comparison_id, with_for_update=True)
    if not item:
        raise HTTPException(404, '找不到该比较结果')
    dataset = db.scalar(select(Dataset).order_by(Dataset.id.desc()).limit(1))
    if not dataset:
        raise HTTPException(409, '尚无可用数据批次')
    params = dict(item.params or {})
    params.update(report_day=item.report_day, lead_days_a=item.lead_days_a,
                  lead_days_b=item.lead_days_b)
    job = enqueue(db, dataset, item.dataset_name, params, actor.username, base_version=item.version)
    db.commit()
    wake()
    return views.comparison_job(job)
