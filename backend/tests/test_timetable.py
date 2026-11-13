from backend.tests.test_env import TestEnvironment

env = TestEnvironment(prefix="kruskal_timetable_")


def setup_module():
    env.setup()


def teardown_module():
    env.teardown()


def test_timetable_slot_roundtrip():
    client, headers = env.client, env.auth_headers()
    date = "2026-11-09"
    day = f"/api/timetable/day?date={date}"

    assert client.get(day, headers=headers).json() == {"items": []}

    # 半小时粒度填两格
    assert client.put("/api/timetable/slot", headers=headers,
                      json={"date": date, "slot_min": 480, "text": "高数", "span": 30}).json() == {"ok": True}
    assert client.put("/api/timetable/slot", headers=headers,
                      json={"date": date, "slot_min": 510, "text": "英语", "span": 30}).status_code == 200
    items = client.get(day, headers=headers).json()["items"]
    assert items == [{"slot_min": 480, "text": "高数"}, {"slot_min": 510, "text": "英语"}]

    # 切 20 分钟行距后覆写 [480,500)：只清该行覆盖到的旧条目，510 不受影响
    assert client.put("/api/timetable/slot", headers=headers,
                      json={"date": date, "slot_min": 480, "text": "高数课", "span": 20}).status_code == 200
    items = client.get(day, headers=headers).json()["items"]
    assert items == [{"slot_min": 480, "text": "高数课"}, {"slot_min": 510, "text": "英语"}]

    # 空文字 = 删除该格
    assert client.put("/api/timetable/slot", headers=headers,
                      json={"date": date, "slot_min": 480, "text": "", "span": 20}).status_code == 200
    items = client.get(day, headers=headers).json()["items"]
    assert items == [{"slot_min": 510, "text": "英语"}]

    # 清空整天
    assert client.delete(day, headers=headers).json() == {"ok": True}
    assert client.get(day, headers=headers).json() == {"items": []}


def test_timetable_validation():
    client, headers = env.client, env.auth_headers()
    assert client.get("/api/timetable/day?date=2026-11-9", headers=headers).status_code == 400
    assert client.get("/api/timetable/day?date=2026-13-40", headers=headers).status_code == 400
    assert client.put("/api/timetable/slot", headers=headers,
                      json={"date": "2026-11-09", "slot_min": 1440, "text": "x", "span": 30}).status_code == 422
    # 未登录被全局中间件拦截
    assert client.get("/api/timetable/day?date=2026-11-09").status_code == 401
