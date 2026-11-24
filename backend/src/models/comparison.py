from datetime import datetime
from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
from src.constants.enums import Status
from src.utils.time import now


class ComparisonJob(Base):
    """历史比较后台任务。``base_version`` 为提交时所见的已发布版本。"""

    __tablename__ = 'comparison_jobs'

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    dataset_name: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(120))
    params: Mapped[dict] = mapped_column(JSON)
    base_version: Mapped[int | None]
    status: Mapped[str] = mapped_column(String(20), default=Status.QUEUED, index=True)
    attempt: Mapped[int] = mapped_column(default=0)
    lease_until: Mapped[datetime | None]
    comparison_id: Mapped[int | None] = mapped_column(ForeignKey('comparisons.id'))
    recomputed: Mapped[list | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(String(500))
    actor: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=now)
    finished_at: Mapped[datetime | None]


class Comparison(Base):
    """两套送校提前量的历史比较发布记录。

    同一 ``scope``（批次名、报告日、两套提前量）只有一行，补录后原地更新：

    - ``revision`` 已发布结果所用的数据批次序号。较小批次不能覆盖较大批次。
    - ``version`` 每次成功发布自增，旧任务带旧 ``version`` 发布时被拒绝。
    - ``result``/``source`` 同时容纳两套方案与解析快照，一次事务整批发布。
    """

    __tablename__ = 'comparisons'
    __table_args__ = (UniqueConstraint('scope'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(220), index=True)
    dataset_name: Mapped[str] = mapped_column(String(120))
    params: Mapped[dict] = mapped_column(JSON)
    report_day: Mapped[str] = mapped_column(String(10))
    lead_days_a: Mapped[int]
    lead_days_b: Mapped[int]
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    revision: Mapped[int] = mapped_column(default=0)
    version: Mapped[int] = mapped_column(default=0)
    result: Mapped[dict | None] = mapped_column(JSON)
    source: Mapped[dict | None] = mapped_column(JSON)
    author: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime | None]


class ComparisonShift(Base):
    """比较证据按 (器具, 班次) 落库，补录重算时只改写受影响班次。"""

    __tablename__ = 'comparison_shifts'
    __table_args__ = (UniqueConstraint('comparison_id', 'asset_id', 'shift'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    comparison_id: Mapped[int] = mapped_column(ForeignKey('comparisons.id'), index=True)
    asset_id: Mapped[str] = mapped_column(String(40))
    shift: Mapped[str] = mapped_column(String(10))
    payload: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(default=now)
