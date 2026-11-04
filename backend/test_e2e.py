"""端到端 API 联动测试：验证所有模块核心功能与数据联动"""
import requests, json, os, sys, time

TS = str(int(time.time()))[-6:]  # 每次运行唯一，保证幂等

BASE = os.getenv("WMS_TEST_BASE", "http://127.0.0.1:8000/api/v1")
S = requests.Session()
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(f"{name} {extra}")
    print(("  ✅" if cond else "  ❌") + f" {name} {extra if not cond else ''}")


def login():
    r = S.post(f"{BASE}/auth/login", json={"username": "admin", "password": "admin123"}).json()
    assert r["code"] == 0, r
    S.headers["token"] = r["data"]["token"]
    return r["data"]["user"]


print("== 1. 认证模块 ==")
user = login()
check("登录获取Token与权限", "*" in user["perms"])
r = S.post(f"{BASE}/auth/login", json={"username": "admin", "password": "wrong"}).json()
check("错误密码拒绝", r["code"] != 0)
r = S.get(f"{BASE}/auth/me").json()
check("获取当前用户", r["code"] == 0 and r["data"]["username"] == "admin")

print("== 2. 基础管理模块 ==")
r = S.get(f"{BASE}/warehouses").json()
check("仓库列表", r["code"] == 0 and len(r["data"]) == 3)
wh_id = r["data"][0]["id"]
r = S.get(f"{BASE}/areas?warehouse_id={wh_id}").json()
check("库区列表(按仓库过滤)", r["code"] == 0 and len(r["data"]) == 5)
r = S.get(f"{BASE}/locations?warehouse_id={wh_id}&size=5").json()
check("库位列表(分页)", r["code"] == 0 and r["data"]["total"] > 0)
loc_id = r["data"]["list"][0]["id"]
loc_code = r["data"]["list"][0]["location_code"]
r = S.get(f"{BASE}/products?size=5").json()
check("商品列表(含库存汇总)", r["code"] == 0 and "stock_qty" in r["data"]["list"][0])
prod_id = r["data"]["list"][0]["id"]
prod_name = r["data"]["list"][0]["product_name"]
prod_sku = r["data"]["list"][0]["sku"]
r = S.get(f"{BASE}/suppliers").json()
sup_id = r["data"][0]["id"]
r = S.get(f"{BASE}/customers").json()
cus_id = r["data"][0]["id"]
check("供应商/客户列表", True)
# 创建商品 -> 修改 -> 删除
SKU = f"TEST{TS}"
r = S.post(f"{BASE}/products", json={"sku": SKU, "product_name": "测试商品", "category": "测试", "unit": "个",
                                     "weight": 0.1, "volume": 0.001, "shelf_life": 0, "is_batch_managed": 0,
                                     "min_stock": 10, "max_stock": 100, "price": 9.9, "status": 1}).json()
check("新增商品", r["code"] == 0, r.get("msg", ""))
test_pid = r["data"]["id"]
r = S.put(f"{BASE}/products/{test_pid}", json={"sku": SKU, "product_name": "测试商品改", "category": "测试", "unit": "个",
                                               "weight": 0.1, "volume": 0.001, "shelf_life": 0, "is_batch_managed": 0,
                                               "min_stock": 10, "max_stock": 100, "price": 19.9, "status": 1}).json()
check("修改商品", r["code"] == 0)
r = S.delete(f"{BASE}/products/{test_pid}").json()
check("删除商品", r["code"] == 0)

print("== 3. 入库管理模块（联动库存） ==")
# 记录入库前库存
r = S.get(f"{BASE}/inventory?product_id={prod_id}").json()
before_qty = (r["data"]["summary"] or {}).get("qty", 0)
r = S.get(f"{BASE}/locations?warehouse_id={wh_id}&status=empty&size=3").json()
empty_before = r["data"]["total"]
# 创建入库单
r = S.post(f"{BASE}/inbound-orders", json={
    "warehouse_id": wh_id, "supplier_id": sup_id,
    "items": [{"product_id": prod_id, "quantity": 100, "batch_no": f"TEST-B{TS}",
               "production_date": "2026-08-01", "expiry_date": "2027-08-01"}]}).json()
check("创建入库单", r["code"] == 0)
in_id = r["data"]["id"]
in_no = r["data"]["order_no"]
r = S.post(f"{BASE}/inbound-orders/{in_id}/approve").json()
check("入库单审核", r["code"] == 0)
r = S.post(f"{BASE}/inbound-orders/{in_id}/confirm", json={"inspections": {}}).json()
check("确认入库", r["code"] == 0, r.get("msg", ""))
# 验证联动：库存+100
r = S.get(f"{BASE}/inventory?product_id={prod_id}").json()
after_qty = (r["data"]["summary"] or {}).get("qty", 0)
check("入库后库存联动 +100", after_qty - before_qty == 100, f"{before_qty}->{after_qty}")
r = S.get(f"{BASE}/batches").json()
check("批次登记联动", any(b["batch_no"] == f"TEST-B{TS}" for b in r["data"]))
r = S.get(f"{BASE}/inventory/moves?move_type=inbound").json()
check("入库流水生成", any(m["ref_no"] == in_no for m in r["data"]["list"]))
r = S.get(f"{BASE}/inspections").json()
check("质检记录生成", any(i["order_no"] == in_no for i in r["data"]))
r = S.get(f"{BASE}/inbound-orders/{in_id}").json()
det_loc = r["data"]["details"][0]["location_id"]
r = S.get(f"{BASE}/locations?warehouse_id={wh_id}&size=500").json()
loc = next((l for l in r["data"]["list"] if l["id"] == det_loc), None)
check("库位状态联动(占用)", loc is not None and loc["status"] == "occupied",
      f"loc {det_loc} status={loc['status'] if loc else 'N/A'}")

print("== 4. 出库管理模块（FIFO分配/发货联动库存） ==")
r = S.get(f"{BASE}/inventory?product_id={prod_id}").json()
inv_id = r["data"]["list"][0]["id"]
avail_before = r["data"]["summary"]["avail"]
r = S.post(f"{BASE}/outbound-orders", json={
    "warehouse_id": wh_id, "customer_id": cus_id, "priority": 1,
    "items": [{"product_id": prod_id, "quantity": 30}]}).json()
check("创建出库单(库存预检)", r["code"] == 0)
out_id = r["data"]["id"]
out_no = r["data"]["order_no"]
r = S.post(f"{BASE}/outbound-orders/{out_id}/approve").json()
check("出库单审核", r["code"] == 0)
r = S.post(f"{BASE}/outbound-orders/{out_id}/allocate").json()
check("FIFO库存分配锁定", r["code"] == 0)
r = S.get(f"{BASE}/inventory?product_id={prod_id}").json()
check("锁定后可用量-30", r["data"]["summary"]["avail"] == avail_before - 30,
      f"{avail_before}->{r['data']['summary']['avail']}")
r = S.get(f"{BASE}/outbound-orders/{out_id}").json()
check("分配明细含批次库位", r["code"] == 0 and len(r["data"]["allocations"]) > 0)
r = S.post(f"{BASE}/outbound-orders/{out_id}/ship").json()
check("发货确认", r["code"] == 0)
r = S.get(f"{BASE}/inventory?product_id={prod_id}").json()
check("发货后库存扣减-30", r["data"]["summary"]["qty"] == after_qty - 30)
check("发货后可用量恢复一致", r["data"]["summary"]["avail"] == r["data"]["summary"]["qty"] - r["data"]["summary"]["locked"])
r = S.get(f"{BASE}/inventory/moves?move_type=outbound").json()
check("出库流水生成", any(m["ref_no"] == out_no for m in r["data"]["list"]))

print("== 5. 库存管理模块（移动/调整/冻结/盘点联动） ==")
# 移动
r = S.get(f"{BASE}/locations?warehouse_id={wh_id}&status=empty&size=1").json()
to_loc = r["data"]["list"][0]["id"]
r = S.post(f"{BASE}/inventory/move", json={"inventory_id": inv_id, "to_location_id": to_loc, "quantity": 10}).json()
check("库存移动", r["code"] == 0, r.get("msg", ""))
r = S.get(f"{BASE}/inventory/moves?move_type=move").json()
check("移库流水生成", r["code"] == 0)
# 调整
r = S.post(f"{BASE}/inventory/adjust", json={"inventory_id": inv_id, "adjust_qty": -5, "reason": "damage"}).json()
check("库存调整(盘亏5)", r["code"] == 0)
r = S.get(f"{BASE}/adjustments").json()
check("调整单生成", r["code"] == 0 and len(r["data"]) > 0)
# 冻结/解冻
r = S.post(f"{BASE}/inventory/freeze", json={"inventory_ids": [inv_id], "action": "freeze"}).json()
check("库存冻结", r["code"] == 0)
r = S.post(f"{BASE}/inventory/freeze", json={"inventory_ids": [inv_id], "action": "unfreeze"}).json()
check("库存解冻", r["code"] == 0)
# 盘点：创建 -> 提交（制造差异）
r = S.post(f"{BASE}/check-orders", json={"warehouse_id": wh_id, "type": "cycle", "blind": 0}).json()
check("创建盘点单", r["code"] == 0, r.get("msg", ""))
ck_id = r["data"]["id"]
r = S.get(f"{BASE}/check-orders/{ck_id}").json()
details = r["data"]["details"]
actuals = {str(d["id"]): d["book_qty"] for d in details}
first = details[0]
actuals[str(first["id"])] = first["book_qty"] - 3  # 制造盘亏差异
r = S.post(f"{BASE}/check-orders/{ck_id}/submit", json={"actuals": actuals}).json()
check("提交盘点结果", r["code"] == 0 and r["data"]["diff_count"] == 1, r.get("msg", ""))
r = S.get(f"{BASE}/adjustments").json()
check("盘点差异自动生成调整单", r["code"] == 0 and any(a["reason"] == "loss" for a in r["data"]))

print("== 6. 智能决策模块 ==")
r = S.get(f"{BASE}/analytics/dashboard").json()
check("数据看板KPI", r["code"] == 0 and r["data"]["kpi"]["total_qty"] > 0)
check("看板趋势/图表数据", len(r["data"]["trend"]) == 14 and len(r["data"]["abc"]["stat"]) == 3)
r = S.get(f"{BASE}/alerts").json()
check("预警扫描", r["code"] == 0 and r["data"]["today_new"] >= 0)
r = S.post(f"{BASE}/replenishment/suggest").json()
check("智能补货建议", r["code"] == 0)
r = S.get(f"{BASE}/replenishment").json()
check("补货建议列表", r["code"] == 0 and len(r["data"]) >= 0)
r = S.get(f"{BASE}/reports/inventory_detail").json()
check("报表生成", r["code"] == 0 and len(r["data"]["rows"]) > 0)
r = requests.get(f"{BASE}/reports/inventory_detail/export", headers={"token": S.headers["token"]})
check("Excel导出", r.status_code == 200 and "spreadsheet" in r.headers.get("content-type", ""))

print("== 7. 系统管理模块 ==")
r = S.get(f"{BASE}/users").json()
check("用户管理列表", r["code"] == 0 and r["data"]["total"] >= 5)
r = S.get(f"{BASE}/roles").json()
check("角色权限列表", r["code"] == 0 and len(r["data"]) == 4)
r = S.get(f"{BASE}/configs").json()
check("系统参数", r["code"] == 0 and len(r["data"]) >= 6
      and any(c["config_key"] == "company_name" for c in r["data"]))
r = S.get(f"{BASE}/logs?size=5").json()
check("操作日志联动记录", r["code"] == 0 and r["data"]["total"] > 10, f"共{r['data']['total']}条")
r = S.get(f"{BASE}/logs?keyword=入库").json()
check("日志搜索", r["code"] == 0)

print("== 8. 权限控制（RBAC） ==")
r = requests.post(f"{BASE}/auth/login", json={"username": "liuyang", "password": "123456"}).json()
viewer_token = r["data"]["token"]
r = requests.get(f"{BASE}/users", headers={"token": viewer_token}).json()
check("观察者无用户管理权限(403)", r.get("code") == 403 or "detail" in r)
r = requests.get(f"{BASE}/reports/inventory_detail", headers={"token": viewer_token}).json()
check("观察者有报表权限", r["code"] == 0)
r = requests.get(f"{BASE}/inventory").json()
check("未登录拒绝(401)", r.get("code") == 401 or "detail" in r)

print("== 9. ASN/波次联动 ==")
r = S.post(f"{BASE}/asn", json={"warehouse_id": wh_id, "supplier_id": sup_id,
                                "items": [{"product_id": prod_id, "quantity": 20}]}).json()
check("创建ASN", r["code"] == 0)
asn_id = r["data"]["id"]
r = S.post(f"{BASE}/asn/{asn_id}/to-inbound").json()
check("ASN转入库单(自动生成批次)", r["code"] == 0)
r = S.get(f"{BASE}/waves").json()
check("波次列表", r["code"] == 0)

print("== 10. 智能客服（RAG 多 Agent） ==")
r = S.get(f"{BASE}/cs/agents").json()
check("Agent 目录", r["code"] == 0 and len(r["data"]["agents"]) == 6)
r = S.get(f"{BASE}/cs/suggestions").json()
check("快捷问题", r["code"] == 0 and len(r["data"]["items"]) >= 4)
r = S.post(f"{BASE}/cs/sessions", json={}).json()
check("创建客服会话", r["code"] == 0)
sid = r["data"]["id"]
r = S.post(f"{BASE}/cs/chat", json={"session_id": sid, "message": f"{prod_name}还有多少库存？"}).json()
check("RAG 库存问答", r["code"] == 0 and r["data"]["intent"]["code"] == "stock"
      and any(t.get("ok") for t in r["data"]["tools"]))
check("回答含知识引用", len(r["data"]["citations"]) > 0)
check("多 Agent 轨迹", len({a["name"] for a in r["data"]["agents"]}) >= 4)
mid = r["data"]["message_id"]
r = S.post(f"{BASE}/cs/messages/{mid}/feedback", json={"rating": 1}).json()
check("回答反馈", r["code"] == 0)
r = S.post(f"{BASE}/cs/kb/search", json={"query": "入库单怎么确认入库", "top_k": 3}).json()
check("知识库检索", r["code"] == 0 and len(r["data"]["hits"]) >= 1)
r = S.get(f"{BASE}/cs/kb?page=1&size=5").json()
check("知识库文档", r["code"] == 0 and r["data"]["total"] >= 17)
r = S.post(f"{BASE}/cs/chat", json={"session_id": sid, "message": "转人工客服"}).json()
check("转人工自动建单", r["code"] == 0 and r["data"]["ticket"] is not None)
cs_ticket = r["data"]["ticket"]
r = S.get(f"{BASE}/cs/tickets").json()
check("工单列表", r["code"] == 0 and r["data"]["total"] >= 1)

print("== 11. 人工接管与实时会话 ==")
hr = requests.post(f"{BASE}/auth/login", json={"username": "zhangwei", "password": "123456"}).json()
agent_token = hr["data"]["token"]
r = requests.get(f"{BASE}/cs/human/queue", headers={"token": agent_token}).json()
check("人工排队列表", r["code"] == 0 and any(t["id"] == cs_ticket["id"] for t in r["data"]["list"]))
r = requests.post(f"{BASE}/cs/tickets/{cs_ticket['id']}/accept", headers={"token": agent_token}).json()
check("坐席接入会话", r["code"] == 0 and r["data"]["human_agent"] == "张伟")
s = S.get(f"{BASE}/cs/sessions/{sid}/messages").json()["data"]["session"]
check("会话转人工状态", s["status"] == "human")
r = requests.post(f"{BASE}/cs/sessions/{sid}/agent-message",
                  headers={"token": agent_token},
                  json={"content": "您好，我是人工客服张伟，请提供单据号。"}).json()
check("坐席发送消息", r["code"] == 0 and r["data"]["sender_name"] == "张伟")
msgs = S.get(f"{BASE}/cs/sessions/{sid}/messages").json()["data"]["messages"]
check("客户可收到坐席消息", any(m["role"] == "agent" and m["sender_name"] == "张伟" for m in msgs))
r = S.post(f"{BASE}/cs/chat", json={"session_id": sid, "message": "单据号 IN20261022030"}).json()
check("人工模式下不触发AI", r["code"] == 0 and r["data"].get("human_mode") is True)
r = requests.post(f"{BASE}/cs/tickets/{cs_ticket['id']}/resolve",
                  headers={"token": agent_token}, json={"resolution": "已通过人工沟通解决"}).json()
check("结束人工服务", r["code"] == 0 and r["data"]["status"] == "resolved")
s = S.get(f"{BASE}/cs/sessions/{sid}/messages").json()["data"]["session"]
check("会话恢复智能客服", s["status"] == "active" and not s["human_agent"])
r = S.post(f"{BASE}/cs/chat", json={"session_id": sid, "message": f"{prod_name}还有多少库存？"}).json()
check("恢复后AI继续回答", r["code"] == 0 and not r["data"].get("human_mode"))
cfg = S.get(f"{BASE}/configs").json()["data"]
partner_key = os.getenv("WMS_PARTNER_KEY") or next(
    (c["config_value"] for c in cfg if c["config_key"] == "partner_api_key"), "wms-partner-demo-key")
r = S.get(f"{BASE}/partner/supplier/SUP001/scorecard", headers={"X-Partner-Key": partner_key}).json()
check("供应商开放接口-履约画像", r["code"] == 0 and r["data"]["supplier"]["supplier_code"] == "SUP001")
r = S.get(f"{BASE}/partner/asns?supplier_code=SUP001", headers={"X-Partner-Key": partner_key}).json()
check("供应商开放接口-ASN查询", r["code"] == 0)
r = S.get(f"{BASE}/partner/asns?supplier_code=SUP001", headers={"X-Partner-Key": "wrong-key"}).json()
check("供应商接口拒绝错误密钥", r.get("code") == 401 or "detail" in r)

print("== 12. 扫码作业 ==")
r = S.get(f"{BASE}/scan/tasks").json()
check("扫码任务统计", r["code"] == 0 and "inbound" in r["data"]["counts"])
r = S.get(f"{BASE}/scan/resolve", params={"code": prod_sku}).json()
check("扫码识别商品", r["code"] == 0 and r["data"]["type"] == "product"
      and r["data"]["data"]["product"]["id"] == prod_id)
r = S.get(f"{BASE}/scan/resolve", params={"code": loc_code}).json()
check("扫码识别库位", r["code"] == 0 and r["data"]["type"] == "location")
r = S.get(f"{BASE}/scan/logs?limit=5").json()
check("扫码日志", r["code"] == 0 and len(r["data"]) >= 1)
r = requests.get(f"{BASE}/scan/tasks", headers={"token": viewer_token}).json()
check("观察者可扫码查询", r["code"] == 0)
r = requests.post(f"{BASE}/scan/move", headers={"token": viewer_token},
                  json={"from_code": "X", "product_code": "Y", "to_code": "Z", "quantity": 1}).json()
check("观察者无移库权限", r.get("code") == 403 or "detail" in r)

print("== 13. 通用问答（日期/计算/寒暄） ==")
r = S.post(f"{BASE}/cs/chat", json={"session_id": sid, "message": "今天是几号？"}).json()
check("日期问答", r["code"] == 0 and r["data"]["intent"]["code"] == "general"
      and time.strftime("%Y") in r["data"]["answer"] and len(r["data"]["citations"]) == 0)
r = S.post(f"{BASE}/cs/chat", json={"session_id": sid, "message": "计算 125*36"}).json()
check("算术问答", r["code"] == 0 and r["data"]["intent"]["code"] == "general"
      and "4500" in r["data"]["answer"])
r = S.post(f"{BASE}/cs/chat", json={"session_id": sid, "message": "谢谢"}).json()
check("寒暄问答", r["code"] == 0 and r["data"]["intent"]["code"] == "general"
      and "不客气" in r["data"]["answer"])

print("\n" + "=" * 50)
print(f"测试结果: 通过 {len(PASS)} / 失败 {len(FAIL)}")
if FAIL:
    print("失败项:")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
print("全部通过 ✔")
