# 001 初始表结构

应用首次启动以 SQLAlchemy 模型创建表与唯一约束。现有数据表只补建缺失表，升级到修改过字段的版本需要显式迁移。

- `users` 账号角色和加盐密码摘要。
- `datasets` 不可变记录批次，以名称和 SHA-256 去重。
- `runs` 记录参数、数据批次、运行租约、分析结果、导出文件及复核决定。
- `schedules` 保存定时计划和下一到期时间。
- `deliveries` 保存站内分发回执，每次运行最多一个回执。
- `audit_events` 记录登录、数据入库、运行、复核和报表分发动作。

## 历史比较（追加表）

随历史比较新增以下表，均由 SQLAlchemy 模型在启动时创建，无需显式迁移：

- `comparison_jobs` 历史比较任务、租约、提交时所见的已发布版本与重算器具清单。
- `comparisons` 按 `scope`（批次名、报告日、两套提前量）唯一的发布记录，携带 `revision`（数据批次序号）与 `version`（发布版本）。
- `comparison_shifts` 按 (器具, 班次) 落库的逐班证据，补录重算时只改写变化的行。

`datasets` 的字段保持不变；新增的检查记录列（`shift`、`inspection_result`、`recorded_on`）随 CSV 导入存放在 `datasets.rows`。

导入仍要求完整表头。旧版 CSV 需先补上这三列（`recorded_on` 可留空，按检查班次同日处理）再导入；已有批次无需重建。
