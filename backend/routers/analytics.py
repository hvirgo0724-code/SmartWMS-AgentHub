"""智能决策：数据看板/库存预警/智能补货/ABC分类/报表导出"""
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from database import query, query_one, execute, transaction, add_log
from deps import get_current_user, require_perm, ok, fail
from datetime import date, timedelta
from typing import Optional
import io

router = APIRouter(tags=["智能决策"])


# ---------- 数据看板 ----------
@router.get("/analytics/dashboard")
def dashboard(user: dict = Depends(get_current_user)):
    # 顶部 KPI
    kpi = {}
    kpi["warehouse_count"] = query_one("SELECT COUNT(*) c FROM wms_warehouse WHERE status=1")["c"]
    kpi["product_count"] = query_one("SELECT COUNT(*) c FROM wms_product WHERE status=1")["c"]
    kpi["total_qty"] = query_one("SELECT COALESCE(SUM(quantity),0) c FROM wms_inventory")["c"]
    kpi["total_value"] = query_one("""SELECT COALESCE(SUM(i.quantity*p.price),0) c FROM wms_inventory i
                                      JOIN wms_product p ON i.product_id=p.id""")["c"]
    kpi["pending_inbound"] = query_one("SELECT COUNT(*) c FROM wms_inbound_order WHERE status IN ('pending','approved')")["c"]
    kpi["pending_outbound"] = query_one("SELECT COUNT(*) c FROM wms_outbound_order WHERE status IN ('pending','approved','allocated')")["c"]
    kpi["shipped_month"] = query_one("""SELECT COUNT(*) c FROM wms_outbound_order
                                        WHERE status='shipped' AND actual_time>=DATE_FORMAT(NOW(),'%%Y-%%m-01')""")["c"]
    # 订单满足率 = 已发货 / (已发货+已取消)
    fr = query_one("""SELECT SUM(status='shipped') s, SUM(status='cancelled') x FROM wms_outbound_order""")
    kpi["fulfill_rate"] = round(fr["s"] / (fr["s"] + fr["x"]) * 100, 1) if (fr["s"] or 0) + (fr["x"] or 0) > 0 else 100

    # 库容利用率
    loc = query_one("SELECT COUNT(*) total, SUM(status='occupied') used FROM wms_location")
    kpi["location_total"] = loc["total"]
    kpi["location_used"] = loc["used"] or 0
    kpi["location_rate"] = round(loc["used"] / loc["total"] * 100, 1) if loc["total"] else 0

    # 出入库趋势（近14天）
    trend = query("""SELECT DATE(create_time) d,
                             SUM(move_type='inbound') inbound_cnt, SUM(move_type='outbound') outbound_cnt
                      FROM wms_stock_move WHERE create_time >= DATE_SUB(CURDATE(), INTERVAL 13 DAY)
                      GROUP BY DATE(create_time) ORDER BY d""")
    trend_days = {str(r["d"]): r for r in trend}
    trend_list = []
    for i in range(13, -1, -1):
        d = date.today() - timedelta(days=i)
        t = trend_days.get(str(d))
        trend_list.append({"date": d.strftime("%m-%d"),
                           "inbound": t["inbound_cnt"] or 0 if t else 0,
                           "outbound": t["outbound_cnt"] or 0 if t else 0})

    # 各仓库库存分布
    wh_stock = query("""SELECT w.warehouse_name name, COALESCE(SUM(i.quantity),0) qty FROM wms_warehouse w
                         LEFT JOIN wms_inventory i ON i.warehouse_id=w.id GROUP BY w.id ORDER BY qty DESC""")

    # 库存价值 Top10 商品
    top_products = query("""SELECT p.product_name name, SUM(i.quantity*p.price) value FROM wms_inventory i
                            JOIN wms_product p ON i.product_id=p.id GROUP BY i.product_id
                            ORDER BY value DESC LIMIT 10""")

    # 商品分类分布
    category = query("""SELECT p.category name, COALESCE(SUM(i.quantity),0) qty FROM wms_inventory i
                        JOIN wms_product p ON i.product_id=p.id GROUP BY p.category ORDER BY qty DESC LIMIT 8""")

    # ABC 分类统计
    abc = abc_data()

    return ok({"kpi": kpi, "trend": trend_list, "wh_stock": wh_stock,
               "top_products": top_products, "category": category, "abc": abc})


def abc_data():
    """ABC 分类：按库存价值累计占比 A<=70% B<=90% C>90%"""
    rows = query("""SELECT p.id, p.sku, p.product_name, SUM(i.quantity*p.price) value, SUM(i.quantity) qty
                    FROM wms_inventory i JOIN wms_product p ON i.product_id=p.id
                    GROUP BY p.id HAVING value>0 ORDER BY value DESC""")
    total = sum(r["value"] for r in rows) or 1
    acc = 0
    stat = {"A": {"count": 0, "value": 0}, "B": {"count": 0, "value": 0}, "C": {"count": 0, "value": 0}}
    for r in rows:
        acc += r["value"]
        ratio = acc / total
        cls = "A" if ratio <= 0.7 else ("B" if ratio <= 0.9 else "C")
        r["class"] = cls
        r["acc_ratio"] = round(ratio * 100, 2)
        stat[cls]["count"] += 1
        stat[cls]["value"] += float(r["value"])
    return {"stat": stat, "items": rows[:50]}


@router.get("/analytics/abc")
def abc_analysis(user: dict = Depends(get_current_user)):
    return ok(abc_data())


# ---------- 库存预警扫描 ----------
@router.get("/alerts")
def scan_alerts(alert_type: Optional[str] = None, user: dict = Depends(get_current_user)):
    """扫描并生成预警：缺货/超储/临期/滞销"""
    rules = {r["rule_type"]: r for r in query("SELECT * FROM wms_alert_rule WHERE enabled=1")}
    today = date.today()
    alerts = []

    # 缺货预警：可用库存 < 安全库存
    for r in query("""SELECT p.id, p.sku, p.product_name, p.min_stock,
                              COALESCE(SUM(i.available_qty),0) avail
                      FROM wms_product p LEFT JOIN wms_inventory i ON i.product_id=p.id
                      WHERE p.min_stock>0 AND p.status=1 GROUP BY p.id HAVING avail < p.min_stock"""):
        alerts.append(("low_stock", "high", r["id"],
                       f"缺货预警：{r['product_name']}({r['sku']}) 可用库存 {r['avail']} 低于安全库存 {r['min_stock']}"))

    # 超储预警：库存 > 上限
    for r in query("""SELECT p.id, p.sku, p.product_name, p.max_stock,
                              COALESCE(SUM(i.quantity),0) qty
                      FROM wms_product p LEFT JOIN wms_inventory i ON i.product_id=p.id
                      WHERE p.max_stock>0 AND p.status=1 GROUP BY p.id HAVING qty > p.max_stock"""):
        alerts.append(("over_stock", "medium", r["id"],
                       f"超储预警：{r['product_name']}({r['sku']}) 库存 {r['qty']} 超过上限 {r['max_stock']}"))

    # 临期预警：批次到期日 <= 阈值天数
    days = rules.get("expiry", {}).get("threshold", 30)
    for r in query("""SELECT b.product_id, p.sku, p.product_name, b.batch_no, b.expiry_date,
                             COALESCE((SELECT SUM(i.quantity) FROM wms_inventory i
                                       WHERE i.product_id=b.product_id AND i.batch_no=b.batch_no),0) qty
                      FROM wms_batch b JOIN wms_product p ON b.product_id=p.id
                      WHERE b.expiry_date IS NOT NULL AND b.expiry_date <= DATE_ADD(CURDATE(), INTERVAL %s DAY)""",
                   (days,)):
        if r["qty"] > 0:
            left = (r["expiry_date"] - today).days
            alerts.append(("expiry", "high" if left <= 7 else "medium", r["product_id"],
                           f"临期预警：{r['product_name']}({r['sku']}) 批次 {r['batch_no']} "
                           f"剩余 {left} 天到期（在库 {r['qty']}）"))

    # 滞销预警：90天无出库且有库存
    for r in query("""SELECT p.id, p.sku, p.product_name, COALESCE(SUM(i.quantity),0) qty
                      FROM wms_product p JOIN wms_inventory i ON i.product_id=p.id
                      WHERE p.id NOT IN (SELECT DISTINCT product_id FROM wms_stock_move
                                         WHERE move_type='outbound' AND create_time>=DATE_SUB(NOW(), INTERVAL 90 DAY))
                      GROUP BY p.id HAVING qty>0"""):
        alerts.append(("dead_stock", "low", r["id"],
                       f"滞销预警：{r['product_name']}({r['sku']}) 90天无出库记录（在库 {r['qty']}）"))

    # 去重写入（当天同类型同商品不重复）
    with transaction() as conn:
        for a_type, level, pid, content in alerts:
            exists = query_one("""SELECT id FROM wms_alert_log WHERE alert_type=%s AND product_id=%s
                                  AND DATE(create_time)=CURDATE()""", (a_type, pid), conn)
            if not exists:
                rule = rules.get(a_type)
                execute("""INSERT INTO wms_alert_log (rule_id, alert_type, level, product_id, content)
                           VALUES (%s,%s,%s,%s,%s)""", (rule["id"] if rule else None, a_type, level, pid, content), conn)

    logs = query("""SELECT l.*, p.sku, p.product_name FROM wms_alert_log l
                    LEFT JOIN wms_product p ON l.product_id=p.id
                    WHERE (%s IS NULL OR l.alert_type=%s)
                    ORDER BY FIELD(l.level, 'high', 'medium', 'low'), l.id DESC LIMIT 100""",
                 (alert_type, alert_type))
    return ok({"alerts": logs, "today_new": len(alerts)})


@router.get("/alert-rules")
def list_alert_rules(user: dict = Depends(get_current_user)):
    return ok(query("SELECT * FROM wms_alert_rule ORDER BY id"))


@router.put("/alert-rules/{rid}")
def update_alert_rule(rid: int, body: dict, user: dict = Depends(require_perm("system:config"))):
    execute("UPDATE wms_alert_rule SET threshold=%s, enabled=%s WHERE id=%s",
            (body.get("threshold", 0), body.get("enabled", 1), rid))
    add_log(None, user, "系统管理", "修改预警规则", f"规则 id={rid}")
    return ok(msg="更新成功")


@router.post("/alerts/{aid}/read")
def mark_read(aid: int, user: dict = Depends(get_current_user)):
    execute("UPDATE wms_alert_log SET is_read=1 WHERE id=%s", (aid,))
    return ok(msg="已标记已读")


# ---------- 智能补货 ----------
@router.post("/replenishment/suggest")
def replenishment_suggest(user: dict = Depends(require_perm("decision:view"))):
    """基于近30天出库速度 + 安全库存 生成补货建议"""
    rows = query("""SELECT p.id, p.sku, p.product_name, p.min_stock, p.max_stock, p.price,
                           COALESCE(SUM(i.quantity),0) stock
                    FROM wms_product p LEFT JOIN wms_inventory i ON i.product_id=p.id
                    WHERE p.status=1 GROUP BY p.id""")
    suggested = []
    with transaction() as conn:
        execute("DELETE FROM wms_replenishment WHERE status='pending'", (), conn)
        for p in rows:
            usage = query_one("""SELECT COALESCE(SUM(quantity),0) q FROM wms_stock_move
                                 WHERE move_type='outbound' AND product_id=%s
                                 AND create_time>=DATE_SUB(NOW(), INTERVAL 30 DAY)""", (p["id"],))["q"]
            avg_daily = round(usage / 30, 1)
            lead_time_days = 7  # 采购周期
            suggest = int(avg_daily * lead_time_days + p["min_stock"] - p["stock"])
            if suggest > 0 and p["min_stock"] > 0:
                reason = f"日均出库{avg_daily}，采购周期7天，安全库存{p['min_stock']}，当前库存{p['stock']}"
                execute("""INSERT INTO wms_replenishment (product_id, current_stock, avg_daily, suggested_qty, reason)
                           VALUES (%s,%s,%s,%s,%s)""", (p["id"], p["stock"], avg_daily, suggest, reason), conn)
                suggested.append({"sku": p["sku"], "name": p["product_name"], "suggest": suggest})
    add_log(None, user, "智能决策", "补货建议", f"重新计算补货建议，生成 {len(suggested)} 条")
    return ok({"count": len(suggested)}, f"已生成 {len(suggested)} 条补货建议")


@router.get("/replenishment")
def list_replenishment(user: dict = Depends(get_current_user)):
    rows = query("""SELECT r.*, p.sku, p.product_name, p.price, p.unit FROM wms_replenishment r
                    JOIN wms_product p ON r.product_id=p.id ORDER BY r.id DESC LIMIT 200""")
    for r in rows:
        r["estimated_cost"] = round((r["suggested_qty"] or 0) * float(r["price"] or 0), 2)
    return ok(rows)


@router.post("/replenishment/{rid}/handle")
def handle_replenishment(rid: int, body: dict, user: dict = Depends(require_perm("decision:view"))):
    status = body.get("status", "ordered")
    execute("UPDATE wms_replenishment SET status=%s WHERE id=%s", (status, rid))
    add_log(None, user, "智能决策", "处理补货建议", f"建议 id={rid} 标记为 {status}")
    return ok(msg="已处理")


# ---------- 报表中心 ----------
def _report_data(report_type: str):
    titles = {
        "inbound_summary": "入库汇总报表",
        "outbound_summary": "出库汇总报表",
        "inventory_detail": "库存明细报表",
        "expiry_analysis": "效期分析报表",
        "performance": "作业绩效报表",
    }
    if report_type not in titles:
        return None, None

    if report_type == "inbound_summary":
        rows = query("""SELECT o.order_no, w.warehouse_name, s.supplier_name, o.status, o.actual_time,
                               d.quantity, d.received_qty, p.sku, p.product_name
                        FROM wms_inbound_order o JOIN wms_inbound_detail d ON d.inbound_id=o.id
                        JOIN wms_product p ON d.product_id=p.id
                        JOIN wms_warehouse w ON o.warehouse_id=w.id
                        LEFT JOIN wms_supplier s ON o.supplier_id=s.id
                        ORDER BY o.id DESC LIMIT 500""")
    elif report_type == "outbound_summary":
        rows = query("""SELECT o.order_no, w.warehouse_name, c.customer_name, o.status, o.actual_time,
                               d.quantity, d.picked_qty, p.sku, p.product_name
                        FROM wms_outbound_order o JOIN wms_outbound_detail d ON d.outbound_id=o.id
                        JOIN wms_product p ON d.product_id=p.id
                        JOIN wms_warehouse w ON o.warehouse_id=w.id
                        LEFT JOIN wms_customer c ON o.customer_id=c.id
                        ORDER BY o.id DESC LIMIT 500""")
    elif report_type == "inventory_detail":
        rows = query("""SELECT w.warehouse_name, l.location_code, p.sku, p.product_name, i.batch_no,
                               i.quantity, i.locked_qty, i.available_qty, i.status, p.price,
                               ROUND(i.quantity*p.price,2) stock_value
                        FROM wms_inventory i JOIN wms_product p ON i.product_id=p.id
                        JOIN wms_location l ON i.location_id=l.id
                        JOIN wms_warehouse w ON i.warehouse_id=w.id ORDER BY stock_value DESC LIMIT 1000""")
    elif report_type == "expiry_analysis":
        rows = query("""SELECT p.sku, p.product_name, b.batch_no, b.production_date, b.expiry_date,
                               p.shelf_life,
                               COALESCE((SELECT SUM(i.quantity) FROM wms_inventory i
                                         WHERE i.product_id=b.product_id AND i.batch_no=b.batch_no),0) stock_qty,
                               DATEDIFF(b.expiry_date, CURDATE()) days_left
                        FROM wms_batch b JOIN wms_product p ON b.product_id=p.id
                        ORDER BY b.expiry_date IS NULL, b.expiry_date LIMIT 300""")
    else:  # performance
        rows = query("""SELECT operator, SUM(move_type='inbound') inbound_ops, SUM(move_type='outbound') outbound_ops,
                               SUM(move_type='move') move_ops, SUM(quantity) total_qty
                        FROM wms_stock_move GROUP BY operator ORDER BY total_qty DESC""")

    return titles[report_type], rows


@router.get("/reports/{report_type}")
def generate_report(report_type: str, user: dict = Depends(require_perm("report:view"))):
    title, rows = _report_data(report_type)
    if title is None:
        return fail("未知报表类型")
    add_log(None, user, "报表中心", "生成报表", f"生成 {title}（{len(rows)}行）")
    return ok({"title": title, "rows": rows})


@router.get("/reports/{report_type}/export")
def export_report(report_type: str, user: dict = Depends(require_perm("report:view"))):
    title, rows = _report_data(report_type)
    if title is None:
        return fail("未知报表类型")
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title[:30]
    if rows:
        headers = list(rows[0].keys())
        ws.append(headers)
        for r in rows:
            ws.append([str(v) if v is not None else "" for v in r.values()])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    add_log(None, user, "报表中心", "导出Excel", f"导出 {title}")
    filename = f"{report_type}_{date.today().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"})


# ---------- 库位热力图 & 拣货路径优化 ----------
import re


def _loc_grid():
    """库位编码 -> 网格坐标。WH001-A0101 => 库区A 第01行 第01列；库区横向排布，区间隔2列通道"""
    rows = query("""SELECT l.id, l.location_code, l.status, a.warehouse_id FROM wms_location l
                    JOIN wms_area a ON l.area_id=a.id""")
    # 库区按字母排序后顺序编号（A=0,B=1,C=2,P=3,R=4），避免 P/R 字母序造成坐标空洞
    letters = sorted({(r["location_code"] or "")[6:7] for r in rows})
    area_map = {c: i for i, c in enumerate(letters)}
    grid = {}
    for r in rows:
        m = re.match(r'^\w+-([A-Z])(\d{2})(\d{2})$', r["location_code"] or '')
        if not m:
            continue
        area_idx = area_map.get(m.group(1), 0)
        grid[r["id"]] = {
            "id": r["id"], "code": r["location_code"], "warehouse_id": r["warehouse_id"],
            "area": m.group(1), "area_idx": area_idx,
            "row": int(m.group(2)), "col": int(m.group(3)),
            "x": area_idx * 12 + int(m.group(3)), "y": int(m.group(2)),
            "status": r["status"],
        }
    return grid


@router.get("/analytics/heatmap")
def location_heatmap(warehouse_id: Optional[int] = None, user: dict = Depends(get_current_user)):
    """库位活跃度热力图：近90天出入库/移库流水次数 + 占用状态"""
    grid = _loc_grid()
    moves = query("""SELECT from_location_id f, to_location_id t FROM wms_stock_move
                     WHERE create_time >= DATE_SUB(NOW(), INTERVAL 90 DAY)""")
    act = {}
    for m in moves:
        if m["f"]:
            act[m["f"]] = act.get(m["f"], 0) + 1
        if m["t"]:
            act[m["t"]] = act.get(m["t"], 0) + 1
    points = [{
        "code": l["code"], "area": l["area"], "x": l["x"], "y": l["y"],
        "activity": act.get(l["id"], 0),
        "occupied": 1 if l["status"] in ("occupied", "locked") else 0,
    } for l in grid.values() if not warehouse_id or l["warehouse_id"] == warehouse_id]
    return ok({"points": points})


def _manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _path_length(start, order):
    total, cur = 0, start
    for p in order:
        total += _manhattan(cur, (p["x"], p["y"]))
        cur = (p["x"], p["y"])
    return total + _manhattan(cur, start)


def _optimize_order(start, points):
    """最近邻构造 + 2-opt 改进（闭环返回起点）"""
    remaining = list(points)
    order, cur = [], start
    while remaining:
        nxt = min(remaining, key=lambda p: _manhattan(cur, (p["x"], p["y"])))
        order.append(nxt)
        remaining.remove(nxt)
        cur = (nxt["x"], nxt["y"])
    path = [start] + order + [start]
    coord = lambda p: (p["x"], p["y"]) if isinstance(p, dict) else p
    improved = True
    while improved:
        improved = False
        for i in range(1, len(path) - 2):
            for j in range(i + 1, len(path) - 1):
                if _manhattan(coord(path[i - 1]), coord(path[j])) + _manhattan(coord(path[i]), coord(path[j + 1])) \
                        < _manhattan(coord(path[i - 1]), coord(path[i])) + _manhattan(coord(path[j]), coord(path[j + 1])):
                    path[i:j + 1] = reversed(path[i:j + 1])
                    improved = True
    return path[1:-1]


@router.get("/analytics/pick-path")
def pick_path(warehouse_id: Optional[int] = None, product_ids: Optional[str] = None,
              user: dict = Depends(get_current_user)):
    """拣货路径优化：最近邻 + 2-opt；巷道曼哈顿距离，每格 2 米"""
    grid = _loc_grid()
    CELL_M = 2

    if product_ids:
        ids = [int(x) for x in product_ids.split(',') if x.strip().isdigit()]
        if not ids:
            return fail("商品ID格式错误")
        placeholders = ",".join(["%s"] * len(ids))
        inv = query(f"""SELECT i.product_id, i.location_id, i.available_qty, p.sku, p.product_name
                        FROM wms_inventory i JOIN wms_product p ON i.product_id=p.id
                        WHERE i.product_id IN ({placeholders}) AND i.available_qty > 0
                        ORDER BY i.available_qty DESC""", tuple(ids))
    else:
        inv = query("""SELECT i.product_id, i.location_id, i.available_qty, p.sku, p.product_name
                       FROM wms_inventory i JOIN wms_product p ON i.product_id=p.id
                       WHERE i.available_qty > 0 AND i.product_id IN (
                           SELECT product_id FROM wms_stock_move WHERE move_type='outbound'
                           AND create_time >= DATE_SUB(NOW(), INTERVAL 90 DAY))
                       ORDER BY i.available_qty DESC LIMIT 150""")

    # 每个商品取一个库位（过滤仓库，可用量最大优先）
    picks = {}
    for r in inv:
        loc = grid.get(r["location_id"])
        if not loc:
            continue
        if warehouse_id and loc["warehouse_id"] != warehouse_id:
            continue
        if r["product_id"] not in picks:
            picks[r["product_id"]] = {
                "product_id": r["product_id"], "sku": r["sku"], "product_name": r["product_name"],
                "available_qty": r["available_qty"], "location_id": r["location_id"],
                "code": loc["code"], "area": loc["area"], "x": loc["x"], "y": loc["y"],
            }
    if len(picks) < 2:
        return fail("可拣选商品不足 2 个，无法优化路径")

    pick_list = list(picks.values())[:12]
    start = (0, 0)
    optimized = _optimize_order(start, pick_list)
    dist_before = _path_length(start, pick_list)
    dist_after = _path_length(start, optimized)
    saving = round((dist_before - dist_after) / dist_before * 100, 1) if dist_before else 0

    add_log(None, user, "智能决策", "路径优化",
            f"优化拣货路径：{len(pick_list)}个拣货点，{dist_before * CELL_M}m -> {dist_after * CELL_M}m，节省{saving}%")
    return ok({
        "picks": pick_list,
        "optimized": optimized,
        "distance_before": dist_before * CELL_M,
        "distance_after": dist_after * CELL_M,
        "saving_pct": saving,
        "cell_meters": CELL_M,
        "start": {"x": 0, "y": 0, "code": "出库口/打包台"},
    })

