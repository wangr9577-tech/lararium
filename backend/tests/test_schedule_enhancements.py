from backend.tests.test_env import TestEnvironment

env = TestEnvironment(prefix='kruskal_schedule_')

def setup_module(): env.setup()
def teardown_module(): env.teardown()

def test_recurrence_and_legacy_updates_preserve_metadata_and_focus():
    c, h = env.client, env.auth_headers()
    body = {'date':'2026-11-12','kind':'daily','type':'task','title':'复习','priority':'high','estimate_min':45,'repeat':'daily','repeat_until':'2026-11-14'}
    r = c.post('/api/schedule', headers=h, json=body)
    assert r.status_code == 201, r.text
    entries = c.get('/api/schedule/range?from=2026-11-12&to=2026-11-14',headers=h).json()['items']
    assert len(entries) == 3 and len({e['series_id'] for e in entries}) == 1
    a,b,d = entries
    assert c.put(f"/api/schedule/{b['id']}/done", headers=h, json={'done': True}).status_code == 200
    focus = c.post('/api/focus/manual',headers=h,json={'date':'2026-11-13','minutes':20,'note':'复习','schedule_id':b['id']}).json()
    legacy = {'date':b['date'],'kind':'daily','type':'task','title':'单次更新','time_start':'','note':''}
    assert c.put(f"/api/schedule/{b['id']}",headers=h,json=legacy).json()['estimate_min'] == 45
    assert c.put(f"/api/schedule/{a['id']}",headers=h,json={**legacy,'date':a['date'],'title':'系列更新','scope':'series'}).status_code == 200
    updated = c.get('/api/schedule/range?from=2026-11-12&to=2026-11-14',headers=h).json()['items']
    assert [e['date'] for e in updated] == ['2026-11-12','2026-11-13','2026-11-14']
    assert all(e['priority']=='high' and e['estimate_min']==45 for e in updated)
    assert updated[1]['done']
    assert c.delete(f"/api/schedule/{a['id']}",headers=h).status_code == 200
    assert len(c.get('/api/schedule/range?from=2026-11-12&to=2026-11-14',headers=h).json()['items']) == 2
    assert c.delete(f"/api/schedule/{b['id']}?scope=series",headers=h).status_code == 200
    records = c.get('/api/focus/records?q=复习',headers=h).json()['items']
    saved = next(x for x in records if x['id']==focus['id'])
    assert saved['minutes'] == 20 and saved['schedule_id'] is None

def test_bad_recurrence_is_rejected_without_insert():
    c,h=env.client,env.auth_headers()
    base={'date':'2028-01-01','kind':'daily','type':'task','title':'失败','repeat':'daily','repeat_until':'2031-01-01'}
    assert c.post('/api/schedule',headers=h,json=base).status_code == 400
    assert not c.get('/api/schedule/day?date=2028-01-01',headers=h).json()['items']
