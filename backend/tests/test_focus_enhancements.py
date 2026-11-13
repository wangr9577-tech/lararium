from backend.tests.test_env import TestEnvironment

env = TestEnvironment(prefix="kruskal_focus_")


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def test_focus_metadata_edit_and_filter():
    client, headers = env.client, env.auth_headers()
    task = client.post('/api/schedule', headers=headers, json={'date': '2026-11-12', 'kind': 'daily', 'type': 'task', 'title': '阅读'}).json()
    record = client.post('/api/focus/manual', headers=headers, json={'date': '2026-11-12', 'minutes': 25, 'note': '阅读', 'source': 'stopwatch', 'schedule_id': task['id']})
    assert record.status_code == 200
    item = record.json()
    assert item['source'] == 'stopwatch' and item['schedule_id'] == task['id']
    changed = client.patch(f"/api/focus/{item['id']}", headers=headers, json={'date': '2026-11-11', 'minutes': 31, 'note': '论文'})
    assert changed.status_code == 200 and changed.json()['minutes'] == 31
    assert changed.json()['source'] == 'stopwatch' and changed.json()['schedule_id'] == task['id']
    assert len(client.get('/api/focus/records?q=论文&from_date=2026-11-11&to_date=2026-11-11', headers=headers).json()['items']) == 1
    assert client.get('/api/focus/records?q=阅读', headers=headers).json()['items'] == []
    assert client.patch(f"/api/focus/{item['id']}", headers=headers, json={'date': '2026-99-99', 'note': ''}).status_code == 400


def test_deleted_task_does_not_block_completed_focus():
    client, headers = env.client, env.auth_headers()
    task = client.post('/api/schedule', headers=headers, json={'date': '2026-11-12', 'kind': 'daily', 'type': 'task', 'title': '临时任务'}).json()
    assert client.delete(f"/api/schedule/{task['id']}", headers=headers).status_code == 200
    response = client.post('/api/focus/manual', headers=headers, json={
        'date': '2026-11-12', 'minutes': 20, 'note': '临时任务',
        'source': 'countdown', 'schedule_id': task['id'],
    })
    assert response.status_code == 200
    record = response.json()
    assert record['minutes'] == 20 and record['note'] == '临时任务'
    assert record['source'] == 'countdown' and record['schedule_id'] is None
    assert client.get('/api/focus/records?q=临时任务', headers=headers).json()['items'][0]['id'] == record['id']
