from src.utils.time import iso


def dataset(item):
    return {'id': item.id, 'name': item.name, 'filename': item.filename, 'row_count': item.row_count,
            'checksum': item.checksum, 'author': item.author, 'created_at': iso(item.created_at)}


def run(item, detail=False):
    item_view = {'id': item.id, 'dataset_id': item.dataset_id, 'name': item.name, 'status': item.status,
                 'author': item.author, 'review': item.review, 'decision': item.decision,
                 'created_at': iso(item.created_at), 'finished_at': iso(item.finished_at),
                 'scheduled_at': iso(item.scheduled_at), 'schedule_id': item.schedule_id,
                 'has_export': bool(item.export_file), 'error': item.error}
    if detail:
        item_view.update(params=item.params, result=item.result, review_note=item.review_note)
    return item_view


def schedule(item):
    from src.domain.spec import SPEC
    return {'id': item.id, 'name': item.name, 'dataset_id': item.dataset_id, 'recipient': item.recipient,
            'next_at': iso(item.next_at), 'repeat_daily': item.repeat_daily, 'enabled': item.enabled,
            'next_report_day': item.params.get(SPEC['schedule_date_param']) if item.enabled else None}


def delivery(item):
    return {'id': item.id, 'run_id': item.run_id, 'recipient': item.recipient,
            'state': item.state, 'detail': item.detail, 'created_at': iso(item.created_at)}


def comparison(item, detail=False):
    """历史比较的发布摘要；``detail`` 附带两套方案的完整结果与逐台依据。"""
    outcome = (item.result or {}).get('comparison') or {}
    view = {
        'id': item.id, 'dataset_name': item.dataset_name, 'report_day': item.report_day,
        'lead_days': {'a': item.lead_days_a, 'b': item.lead_days_b},
        'dataset_id': item.dataset_id, 'revision': item.revision, 'version': item.version,
        'author': item.author, 'published_at': iso(item.published_at),
        'bounds': outcome.get('bounds'),
        'unsolved_count': len(outcome.get('unsolved', [])),
    }
    if detail:
        view['result'] = item.result
        view['comparison'] = outcome
    return view


def comparison_job(item):
    return {'id': item.id, 'dataset_id': item.dataset_id, 'dataset_name': item.dataset_name,
            'name': item.name, 'status': item.status, 'attempt': item.attempt,
            'comparison_id': item.comparison_id, 'recomputed': item.recomputed or [],
            'error': item.error, 'actor': item.actor,
            'created_at': iso(item.created_at), 'finished_at': iso(item.finished_at)}
