import copy
import json
import threading

import pytest

from mission_control.builtin_plugins import prepare_builtin_agenda_plugins
from mission_control.builtin_plugins.open_requests import TRACKER
from mission_control.database import Database
from mission_control.server import MissionControlApplication


def app_at(tmp_path, plugins=("open-requests",)):
    return MissionControlApplication(Database(tmp_path / 'mc.db'), builtin_plugins=prepare_builtin_agenda_plugins(plugins), write_token='test-token')


def snapshot(app):
    detail = app.entity_detail('open-requests', 'tracker', 'requests')
    return detail['revision'], [json.loads(a['value']) for a in detail['attributes']]


def request():
    return dict(title='Review report', description='Check findings', status='open', next_step='Read the result', tags=['Home', 'home'], task_links=[dict(plugin_id='core', entity_type='task', entity_id='task-123')], work_links=[dict(label='Work', url='https://example.com/work')], result_links=[dict(label='Document', url='https://docs.google.com/document/d/example/edit')])


def command(app, cid, operation, args, revision=None):
    return app.execute_command(dict(schema_version='mission-control.command/v1', command_id=cid, target=TRACKER, expected_revision=revision or snapshot(app)[0], command=operation, arguments=args), authorized=True)


def test_persistence_links_tags_history_close_reopen_and_isolation(tmp_path):
    app = app_at(tmp_path, ('open-requests', 'family-rewards'))
    rewards_before = app.entity_detail('family-rewards','account','family-credit')
    _, result = command(app, 'create1', 'create-request', {'request': request()})
    assert result['status'] == 'accepted'
    rid = result['result']['request_id']
    _, rows = snapshot(app)
    assert rows[0]['tags'] == ['home']
    assert rows[0]['task_links'] == request()['task_links']
    assert any(entry["source"]["plugin_id"] == "open-requests" for entry in app.dashboard()["agenda"])
    original_created_at = rows[0]['created_at']
    # A second request may link the same work, and one request may have many tasks.
    second = request()
    second['task_links'].append(dict(plugin_id='core', entity_type='task', entity_id='task-456'))
    assert command(app, 'create2', 'create-request', {'request': second})[1]['status'] == 'accepted'
    for index, state in enumerate(('ready', 'closed', 'open')):
        updated = request() | {'status': state}
        assert command(app, f'update{index}', 'update-request', {'request_id': rid, 'request': updated})[1]['status'] == 'accepted'
        assert app.entity_detail('open-requests','request',rid)['state'] == state
    restarted = app_at(tmp_path)
    assert snapshot(restarted) == snapshot(app)
    current = next(r for r in snapshot(app)[1] if r['id'] == rid)
    assert current['created_at'] == original_created_at
    assert len(app.entity_detail('open-requests','request',rid)['activity']) == 4
    assert app.entity_detail('family-rewards','account','family-credit') == rewards_before


def test_idempotency_stale_revision_and_concurrent_edits(tmp_path):
    app = app_at(tmp_path)
    rev = snapshot(app)[0]
    args = {'request': request()}
    first = command(app, 'same-id', 'create-request', args, rev)
    assert command(app, 'same-id', 'create-request', args, rev) == first
    assert command(app, 'same-id', 'create-request', {'request': request() | {'title': 'Changed'}}, rev)[1]['status'] == 'rejected'
    assert command(app, 'stale', 'create-request', args, rev)[1]['status'] == 'stale'
    assert len(snapshot(app)[1]) == 1
    rev = snapshot(app)[0]
    barrier = threading.Barrier(3)
    outcomes = []
    def create(cid):
        barrier.wait()
        outcomes.append(command(app, cid, 'create-request', args, rev)[1]['status'])
    threads = [threading.Thread(target=create, args=(str(i),)) for i in range(2)]
    for t in threads: t.start()
    barrier.wait()
    for t in threads: t.join()
    assert sorted(outcomes) == ['accepted', 'stale']


@pytest.mark.parametrize('patch', [
    {'title': ''}, {'unexpected': True}, {'tags': [None]}, {'status': 'done'},
    {'task_links': [{'plugin_id': 'core'}]},
    {'work_links': [{'label': 'Unsafe', 'url': 'javascript:alert(1)'}]},
    {'work_links': [{'label': 'Credentials', 'url': 'https://user:pass@example.com'}]},
    {'result_links': [{'label': 'Broken', 'url': 'https://[invalid'}]},
    {'result_links': [{'label': 'Broken', 'url': 'https://example.com:abc'}]},
    {'next_step': 'x' * 513}, {'result_links': [{'label': 'Large', 'url': 'https://example.com/'+'x'*900}] * 6},
])
def test_invalid_input_does_not_mutate(tmp_path, patch):
    app = app_at(tmp_path)
    before = snapshot(app)
    _, result = command(app, 'bad', 'create-request', {'request': request() | patch})
    assert result['status'] == 'rejected'
    assert snapshot(app) == before


def test_missing_request_and_authorization(tmp_path):
    app = app_at(tmp_path)
    assert command(app,'missing','update-request',{'request_id':'missing','request': request()})[1]['status'] == 'rejected'
    status, _ = app.execute_command(dict(schema_version='mission-control.command/v1', command_id='unauthorized', target=TRACKER, expected_revision='r1', command='create-request', arguments={'request':request()}), authorized=False)
    assert status == 403
    assert snapshot(app) == ('r1', [])


def test_schema_matches_valid_request():
    from importlib.resources import files
    from jsonschema import Draft202012Validator
    schema = json.loads(files('mission_control.builtin_plugins.open_requests').joinpath('request.schema.json').read_text())
    Draft202012Validator(schema).validate(request())
