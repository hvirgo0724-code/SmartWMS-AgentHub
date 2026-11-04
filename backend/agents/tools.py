"""业务工具集：把 WMS 现有能力封装为 Agent 可调用的“工具”（只读查询）"""
import re
import time

from database import query, query_one
from agents.text import tokenize

_CACHE = {}
_TTL = 60


def _cached(key, loader):
    now = time.time()
    item = _CACHE.get(key)
    if item and now - item[0] < _TTL:
        return item[1]
    data = loader()
    _CACHE[key] = (now, data)
    return data


def invalidate_tool_cache():
    _CACHE.clear()


# ---------- 实体识别 ----------
def _products():
    return _cached("products", lambda: query("""SELECT id, sku, product_name, category, unit,
        min_stock, max_stock, price, supplier_id FROM wms_product WHERE status=1 ORDER BY id"""))


def _warehouses():
    return _cached("warehouses", lambda: query("SELECT id, warehouse_code, warehouse_name FROM wms_warehouse WHERE status=1"))


def _suppliers():
    return _cached("suppliers", lambda: query("SELECT id, supplier_code, supplier_name, contact, phone FROM wms_supplier WHERE status=1 ORDER BY id"))


def _customers():
    return _cached("customers", lambda: query("SELECT id, customer_code, customer_name FROM wms_customer WHERE status=1 ORDER BY id"))


def _bigrams(text):
    text = re.sub(r"[\s，。！？、；：,\.\!\?;:]+", "", text or "")
    return {text[i:i + 2] for i in range(len(text) - 1)} if len(text) >= 2 else {text}


def match_products(text, limit=3):
    """从问题中识别商品：SKU 精确 > 名称包含 > 字符重叠度"""
    if not text:
        return []
    up = text.upper()
    hits = []
    q_bg = _bigrams(text)
    for p in _products():
        score = 0.0
        if p["sku"] and p["sku"].upper() in up:
            score = 1.0
        elif p["product_name"] and p["product_name"] in text:
            score = 0.95
        else:
            name_bg = _bigrams(p["product_name"])
            if not name_bg:
                continue
            overlap = len(q_bg & name_bg)
            if overlap >= 2:
                score = overlap / max(len(name_bg), 1) * 0.8
            elif overlap == 1 and len(p["product_name"]) <= 4:
                score = 0.45
        if score >= 0.28:
            hits.append((score, p))
    hits.sort(key=lambda x: x[0], reverse=True)
    if hits:
        # 命中明确商品后过滤弱相关项，避免一个问题带出多个商品
        floor = max(0.28, hits[0][0] * 0.55)
        hits = [h for h in hits if h[0] >= floor]
    return [dict(p, match_score=round(s, 3)) for s, p in hits[:limit]]


def match_warehouse(text):
    if not text:
        return None
    for w in _warehouses():
        name = w["warehouse_name"] or ""
        if name in text or (w["warehouse_code"] and w["warehouse_code"].upper() in text.upper()):
            return w
        # “上海仓”“广州仓”这类简称
        if len(text) >= 2 and name[:2] in text and "仓" in text:
            return w
    return None


def match_supplier(text):
    if not text:
        return None
    q_bg = _bigrams(text)
    best = (0, None)
    for s in _suppliers():
        name = s["supplier_name"] or ""
        if name in text or (s["supplier_code"] and s["supplier_code"].upper() in text.upper()):
            return s
        if len(text) >= 2 and name[:2] and name[:2] in text:
            score = 0.6
        else:
            name_bg = _bigrams(name)
            overlap = len(q_bg & name_bg)
            score = overlap / max(len(name_bg), 1) * 0.8 if overlap >= 2 else 0
        if score > best[0]:
            best = (score, s)
    return best[1] if best[0] >= 0.4 else None


def match_customer(text):
    if not text:
        return None
    for c in _customers():
        if c["customer_name"] in text or (c["customer_code"] and c["customer_code"].upper() in text.upper()):
            return c
    return None


ORDER_NO_RE = re.compile(r"(?<![A-Z0-9])(ASN|IN|OUT|WAVE|QC|CK|ADJ)[A-Z0-9]{6,}", re.I)

STATUS_CN = {
    "pending": "待处理", "approved": "已审核/待收货", "received": "已收货",
    "allocated": "已分配", "picked": "已拣货", "shipped": "已发货",
    "completed": "已完成", "cancelled": "已取消", "checking": "盘点中",
    "pass": "合格", "partial": "部分合格", "unqualified": "不合格",
}


def _st(value):
    return STATUS_CN.get(value, value)


def extract_order_no(text):
    m = ORDER_NO_RE.search((text or "").upper())
    return m.group(0) if m else None


# ---------- 工具实现 ----------
def tool_stock(user, slots):
    products = slots.get("products") or match_products(slots.get("query", ""))
    warehouse = slots.get("warehouse")
    if not products:
        if warehouse:
            stat = query_one("""SELECT COALESCE(SUM(quantity),0) qty, COALESCE(SUM(available_qty),0) avail,
                                       COUNT(DISTINCT product_id) skus, COUNT(DISTINCT location_id) locs
                                FROM wms_inventory WHERE warehouse_id=%s""", (warehouse["id"],))
            loc = query_one("""SELECT COUNT(*) total, SUM(status='occupied') used FROM wms_location l
                               JOIN wms_area a ON l.area_id=a.id WHERE a.warehouse_id=%s""", (warehouse["id"],))
            rate = round((loc["used"] or 0) / (loc["total"] or 1) * 100, 1)
            summary = (f"{warehouse['warehouse_name']}当前库存：{stat['qty']} 件，可用 {stat['avail']}，"
                       f"涉及 {stat['skus']} 个 SKU、{stat['locs']} 个库位；库位利用率 {rate}%（{loc['used'] or 0}/{loc['total']}）。"
                       "如需查询具体商品，请提供商品名称或 SKU。")
            return {"ok": True, "title": "仓库库存概览", "summary": summary,
                    "data": {"warehouse": warehouse, "stat": stat, "location_rate": rate}, "link": "inventory"}
        return {"ok": False, "title": "库存查询",
                "summary": "未识别到具体商品。请提供 SKU 或商品名称（例如：蒙牛纯牛奶 还有多少库存？）", "data": {}}
    rows = []
    for p in products:
        sql = """SELECT i.warehouse_id, w.warehouse_name, SUM(i.quantity) qty,
                        SUM(i.locked_qty) locked, SUM(i.available_qty) avail
                 FROM wms_inventory i JOIN wms_warehouse w ON i.warehouse_id=w.id
                 WHERE i.product_id=%s"""
        params = [p["id"]]
        if warehouse:
            sql += " AND i.warehouse_id=%s"
            params.append(warehouse["id"])
        sql += " GROUP BY i.warehouse_id, w.warehouse_name ORDER BY qty DESC"
        wh = query(sql, params)
        total = sum(r["qty"] or 0 for r in wh)
        avail = sum(r["avail"] or 0 for r in wh)
        locked = sum(r["locked"] or 0 for r in wh)
        batches = query("""SELECT COUNT(*) c FROM wms_inventory WHERE product_id=%s AND quantity>0""", (p["id"],))[0]["c"]
        low = bool(p["min_stock"]) and avail < p["min_stock"]
        rows.append({"sku": p["sku"], "name": p["product_name"], "unit": p["unit"],
                     "total": total, "available": avail, "locked": locked, "batches": batches,
                     "min_stock": p["min_stock"], "max_stock": p["max_stock"],
                     "status": "低于安全库存" if low else "库存正常",
                     "warehouses": wh})
    text = []
    for r in rows:
        text.append(f"{r['name']}（{r['sku']}）：总库存 {r['total']}{r['unit']}，可用 {r['available']}，"
                    f"锁定 {r['locked']}；安全库存 {r['min_stock']}，状态：{r['status']}")
        if r["warehouses"]:
            text.append("仓库分布：" + "；".join(f"{w['warehouse_name']} {w['qty']}" for w in r["warehouses"]))
    return {"ok": True, "title": "实时库存查询", "summary": "\n".join(text),
            "data": {"products": rows, "warehouse": warehouse["warehouse_name"] if warehouse else "全部仓库"}}


def tool_order(user, slots):
    no = slots.get("order_no")
    if not no:
        return {"ok": False, "title": "单据查询", "summary": "请提供单据编号（如 IN20260825001 / ASN20260825001 / OUT2026…）。", "data": {}}
    prefix = re.match(r"[A-Z]+", no).group(0)
    no = no.upper()
    if prefix == "ASN":
        row = query_one("""SELECT a.*, w.warehouse_name, s.supplier_name FROM wms_asn a
                           JOIN wms_warehouse w ON a.warehouse_id=w.id
                           LEFT JOIN wms_supplier s ON a.supplier_id=s.id WHERE a.asn_no=%s""", (no,))
        if not row:
            return {"ok": False, "title": "ASN 查询", "summary": f"未找到收货通知 {no}", "data": {}}
        items = query("""SELECT p.sku, p.product_name, d.quantity FROM wms_asn_detail d
                         JOIN wms_product p ON d.product_id=p.id WHERE d.asn_id=%s""", (row["id"],))
        summary = (f"ASN {no}：状态 {_st(row['status'])}，仓库 {row['warehouse_name']}，"
                   f"供应商 {row['supplier_name'] or '-'}，预计到货 {row['expected_time'] or '-'}；"
                   f"明细 " + "、".join(f"{i['product_name']}×{i['quantity']}" for i in items))
        return {"ok": True, "title": "ASN 收货通知", "summary": summary,
                "data": {"order": row, "items": items}, "link": "asn"}
    if prefix == "IN":
        row = query_one("""SELECT o.*, w.warehouse_name, s.supplier_name FROM wms_inbound_order o
                           JOIN wms_warehouse w ON o.warehouse_id=w.id
                           LEFT JOIN wms_supplier s ON o.supplier_id=s.id WHERE o.order_no=%s""", (no,))
        if not row:
            return {"ok": False, "title": "入库单查询", "summary": f"未找到入库单 {no}", "data": {}}
        items = query("""SELECT p.sku, p.product_name, d.quantity, d.received_qty, d.batch_no
                         FROM wms_inbound_detail d JOIN wms_product p ON d.product_id=p.id
                         WHERE d.inbound_id=%s""", (row["id"],))
        summary = (f"入库单 {no}：状态 {_st(row['status'])}，仓库 {row['warehouse_name']}，"
                   f"供应商 {row['supplier_name'] or '-'}，创建时间 {row['create_time']}；"
                   f"明细 " + "、".join(f"{i['product_name']}×{i['quantity']}（已收 {i['received_qty']}）" for i in items))
        return {"ok": True, "title": "入库单状态", "summary": summary,
                "data": {"order": row, "items": items}, "link": "inbound"}
    if prefix == "OUT":
        row = query_one("""SELECT o.*, w.warehouse_name, c.customer_name FROM wms_outbound_order o
                           JOIN wms_warehouse w ON o.warehouse_id=w.id
                           LEFT JOIN wms_customer c ON o.customer_id=c.id WHERE o.order_no=%s""", (no,))
        if not row:
            return {"ok": False, "title": "出库单查询", "summary": f"未找到出库单 {no}", "data": {}}
        items = query("""SELECT p.sku, p.product_name, d.quantity, d.picked_qty, d.batch_no
                         FROM wms_outbound_detail d JOIN wms_product p ON d.product_id=p.id
                         WHERE d.outbound_id=%s""", (row["id"],))
        summary = (f"出库单 {no}：状态 {_st(row['status'])}，仓库 {row['warehouse_name']}，"
                   f"客户 {row['customer_name'] or '-'}，优先级 {row['priority']}；"
                   f"明细 " + "、".join(f"{i['product_name']}×{i['quantity']}（已拣 {i['picked_qty']}）" for i in items))
        return {"ok": True, "title": "出库单状态", "summary": summary,
                "data": {"order": row, "items": items}, "link": "outbound"}
    if prefix == "WAVE":
        row = query_one("SELECT * FROM wms_wave WHERE wave_no=%s", (no,))
        if not row:
            return {"ok": False, "title": "波次查询", "summary": f"未找到波次 {no}", "data": {}}
        return {"ok": True, "title": "波次拣货", "summary": f"波次 {no}：状态 {_st(row['status'])}，订单数 {row['order_count']}，拣货策略 {row['strategy']}",
                "data": {"order": row}, "link": "waves"}
    if prefix == "QC":
        row = query_one("""SELECT i.*, p.product_name FROM wms_inspection i
                           JOIN wms_product p ON i.product_id=p.id WHERE i.inspection_no=%s""", (no,))
        if not row:
            return {"ok": False, "title": "质检查询", "summary": f"未找到质检单 {no}", "data": {}}
        return {"ok": True, "title": "质检记录",
                "summary": f"质检单 {no}：商品 {row['product_name']}，数量 {row['quantity']}，合格 {row['qualified_qty']}，不合格 {row['unqualified_qty']}，结果 {_st(row['result'])}",
                "data": {"order": row}, "link": "inspections"}
    if prefix == "CK":
        row = query_one("SELECT * FROM wms_check_order WHERE check_no=%s", (no,))
        if not row:
            return {"ok": False, "title": "盘点单查询", "summary": f"未找到盘点单 {no}", "data": {}}
        diffs = query("SELECT COUNT(*) c FROM wms_check_detail WHERE check_id=%s AND diff_qty<>0", (row["id"],))[0]["c"]
        return {"ok": True, "title": "盘点单", "summary": f"盘点单 {no}：状态 {_st(row['status'])}，类型 {row['type']}，差异 {diffs} 条",
                "data": {"order": row}, "link": "checks"}
    if prefix == "ADJ":
        row = query_one("""SELECT a.*, p.product_name FROM wms_adjustment a
                           JOIN wms_product p ON a.product_id=p.id WHERE a.adjust_no=%s""", (no,))
        if not row:
            return {"ok": False, "title": "调整单查询", "summary": f"未找到调整单 {no}", "data": {}}
        return {"ok": True, "title": "库存调整单",
                "summary": f"调整单 {no}：商品 {row['product_name']}，调整前 {row['before_qty']} → 调整后 {row['after_qty']}（{row['reason']}）",
                "data": {"order": row}, "link": "adjustments"}
    return {"ok": False, "title": "单据查询", "summary": f"无法识别的单据号 {no}", "data": {}}


def tool_alerts(user, slots):
    counts = query("""SELECT alert_type, COUNT(*) c FROM wms_alert_log
                      WHERE create_time>=DATE_SUB(NOW(), INTERVAL 7 DAY) GROUP BY alert_type""")
    recent = query("""SELECT l.*, p.product_name, p.sku FROM wms_alert_log l
                      LEFT JOIN wms_product p ON l.product_id=p.id
                      ORDER BY FIELD(l.level,'high','medium','low'), l.id DESC LIMIT 6""")
    label = {"low_stock": "缺货", "over_stock": "超储", "expiry": "临期", "dead_stock": "滞销"}
    if counts:
        lines = ["近 7 天预警统计：" + "、".join(
            f"{label.get(c['alert_type'], c['alert_type'])} {c['c']} 条" for c in counts)]
        lines += [f"- [{r['level']}] {r['content']}" for r in recent[:4]]
        data = {"counts": counts, "recent": recent, "live": False}
    else:
        # 预警日志尚未扫描时，实时兜底统计，避免回答“暂无数据”
        low = query_one("""SELECT COUNT(*) c FROM (
                             SELECT p.id, p.min_stock, COALESCE(SUM(i.available_qty),0) avail
                             FROM wms_product p LEFT JOIN wms_inventory i ON i.product_id=p.id
                             WHERE p.min_stock>0 AND p.status=1 GROUP BY p.id, p.min_stock
                             HAVING avail < p.min_stock) t""")["c"]
        over = query_one("""SELECT COUNT(*) c FROM (
                              SELECT p.id, p.max_stock, COALESCE(SUM(i.quantity),0) qty
                              FROM wms_product p LEFT JOIN wms_inventory i ON i.product_id=p.id
                              WHERE p.max_stock>0 AND p.status=1 GROUP BY p.id, p.max_stock
                              HAVING qty > p.max_stock) t""")["c"]
        exp = query_one("""SELECT COUNT(*) c FROM wms_batch b
                           WHERE b.expiry_date IS NOT NULL AND b.expiry_date<=DATE_ADD(CURDATE(), INTERVAL 30 DAY)""")["c"]
        dead = query_one("""SELECT COUNT(*) c FROM (
                             SELECT p.id FROM wms_product p JOIN wms_inventory i ON i.product_id=p.id
                             WHERE p.id NOT IN (SELECT DISTINCT product_id FROM wms_stock_move
                                                WHERE move_type='outbound' AND create_time>=DATE_SUB(NOW(), INTERVAL 90 DAY))
                             GROUP BY p.id HAVING SUM(i.quantity)>0) t""")["c"]
        lines = [f"预警日志尚未生成，已实时扫描：缺货 {low} 个商品、超储 {over} 个、临期/过期批次 {exp} 个、滞销 {dead} 个。",
                 "可前往「智能决策 → 预警中心」执行扫描，生成可跟踪的预警记录。"]
        data = {"counts": [], "recent": [], "live": True,
                "live_counts": {"low_stock": low, "over_stock": over, "expiry": exp, "dead_stock": dead}}
    return {"ok": True, "title": "预警中心", "summary": "\n".join(lines),
            "data": data, "link": "alerts"}


def _pending_replenishments():
    """优先读取已生成的补货建议；若尚未计算，则按同一公式实时兜底计算"""
    rows = query("""SELECT r.*, p.sku, p.product_name, p.unit, p.supplier_id,
                           COALESCE(s.supplier_name, '未指定默认供应商') supplier_name,
                           COALESCE(s.supplier_code, '') supplier_code,
                           COALESCE(s.contact, '') contact, COALESCE(s.phone, '') phone
                    FROM wms_replenishment r
                    JOIN wms_product p ON r.product_id=p.id
                    LEFT JOIN wms_supplier s ON p.supplier_id=s.id
                    WHERE r.status='pending' ORDER BY r.suggested_qty DESC LIMIT 30""")
    if rows:
        return rows, False
    live = query("""SELECT p.sku, p.product_name, p.unit, p.min_stock, p.supplier_id,
                           COALESCE(s.supplier_name, '未指定默认供应商') supplier_name,
                           COALESCE(s.supplier_code, '') supplier_code,
                           COALESCE(s.contact, '') contact, COALESCE(s.phone, '') phone,
                           COALESCE((SELECT SUM(i.quantity) FROM wms_inventory i
                                     WHERE i.product_id=p.id),0) stock,
                           COALESCE((SELECT SUM(m.quantity) FROM wms_stock_move m
                                     WHERE m.move_type='outbound' AND m.product_id=p.id
                                     AND m.create_time>=DATE_SUB(NOW(), INTERVAL 30 DAY)),0) usage30
                    FROM wms_product p LEFT JOIN wms_supplier s ON p.supplier_id=s.id
                    WHERE p.status=1 ORDER BY p.id""")
    out = []
    for p in live:
        avg_daily = round(float(p["usage30"] or 0) / 30, 1)
        stock = int(p["stock"] or 0)
        suggest = int(avg_daily * 7 + (p["min_stock"] or 0) - stock)
        if suggest > 0 and (p["min_stock"] or 0) > 0:
            out.append({
                "sku": p["sku"], "product_name": p["product_name"], "unit": p["unit"],
                "supplier_id": p["supplier_id"], "supplier_name": p["supplier_name"],
                "supplier_code": p["supplier_code"], "contact": p["contact"], "phone": p["phone"],
                "current_stock": stock, "avg_daily": avg_daily, "suggested_qty": suggest,
                "reason": f"日均出库{avg_daily}，采购周期7天，安全库存{p['min_stock']}，当前库存{stock}",
            })
    out.sort(key=lambda x: x["suggested_qty"], reverse=True)
    return out[:30], True


def tool_replenishment(user, slots):
    rows, live = _pending_replenishments()
    if not rows:
        return {"ok": True, "title": "智能补货", "summary": "当前没有待处理的补货建议，库存水位整体健康。",
                "data": {"items": [], "groups": []}, "link": "replenishment"}
    groups = {}
    for r in rows:
        key = r["supplier_name"] or "未指定默认供应商"
        groups.setdefault(key, {"supplier": key, "count": 0, "qty": 0})
        groups[key]["count"] += 1
        groups[key]["qty"] += r["suggested_qty"] or 0
    head = f"{'实时计算' if live else '已生成'} {len(rows)} 条补货建议（按建议量排序）："
    lines = [head]
    lines += [f"- {r['product_name']}（{r['sku']}）：现有 {r['current_stock']}，建议补 {r['suggested_qty']}（{r['reason']}）" for r in rows[:6]]
    lines.append("按供应商汇总：" + "；".join(f"{g['supplier']} {g['count']} 项/共 {g['qty']} 件" for g in groups.values()))
    return {"ok": True, "title": "补货建议与供应商分组", "summary": "\n".join(lines),
            "data": {"items": rows[:12], "groups": list(groups.values()), "live": live}, "link": "replenishment"}


def tool_locations(user, slots):
    stat = query_one("""SELECT COUNT(*) total, SUM(status='occupied') occupied,
                               SUM(status='empty') empty, SUM(status='locked') locked
                        FROM wms_location""")
    by_wh = query("""SELECT w.warehouse_name, COUNT(l.id) total, SUM(l.status='occupied') used
                     FROM wms_location l JOIN wms_area a ON l.area_id=a.id
                     JOIN wms_warehouse w ON a.warehouse_id=w.id GROUP BY w.id ORDER BY total DESC""")
    rate = round((stat["occupied"] or 0) / (stat["total"] or 1) * 100, 1)
    lines = [f"库位总数 {stat['total']}，占用 {stat['occupied'] or 0}，空闲 {stat['empty'] or 0}，锁定 {stat['locked'] or 0}，利用率 {rate}%"]
    lines += [f"- {w['warehouse_name']}：{w['used'] or 0}/{w['total']} 占用" for w in by_wh]
    return {"ok": True, "title": "库容利用率", "summary": "\n".join(lines),
            "data": {"stat": stat, "by_warehouse": by_wh}, "link": "locations"}


def tool_expiring(user, slots):
    rows = query("""SELECT p.sku, p.product_name, b.batch_no, b.expiry_date,
                           COALESCE(SUM(i.quantity),0) qty,
                           DATEDIFF(b.expiry_date, CURDATE()) days
                    FROM wms_batch b JOIN wms_product p ON b.product_id=p.id
                    LEFT JOIN wms_inventory i ON i.product_id=b.product_id AND i.batch_no=b.batch_no
                    WHERE b.expiry_date IS NOT NULL AND b.expiry_date<=DATE_ADD(CURDATE(), INTERVAL 30 DAY)
                    GROUP BY b.id HAVING qty>0 ORDER BY b.expiry_date LIMIT 10""")
    if not rows:
        return {"ok": True, "title": "批次效期", "summary": "未来 30 天内没有临期批次，效期状态良好。", "data": {"items": []}, "link": "batches"}
    expired = sum(1 for r in rows if (r["days"] or 0) < 0)
    lines = [f"未来 30 天临期 / 已过期批次共 {len(rows)} 条（已过期 {expired} 条）："]
    for r in rows:
        state = f"已过期 {abs(r['days'])} 天" if (r["days"] or 0) < 0 else f"剩余 {r['days']} 天"
        lines.append(f"- {r['product_name']} 批次 {r['batch_no']}：{state}，在库 {r['qty']}")
    lines.append("已过期批次不可继续发货，请冻结并走库存调整（原因 expiry）；临期批次建议优先出库或与供应商协商。")
    return {"ok": True, "title": "批次效期预警", "summary": "\n".join(lines),
            "data": {"items": rows, "expired": expired}, "link": "batches"}


def tool_overview(user, slots):
    def c(sql):
        return query_one(sql)["c"]
    data = {
        "pending_inbound": c("SELECT COUNT(*) c FROM wms_inbound_order WHERE status IN ('pending','approved')"),
        "pending_outbound": c("SELECT COUNT(*) c FROM wms_outbound_order WHERE status IN ('pending','approved','allocated')"),
        "pending_asn": c("SELECT COUNT(*) c FROM wms_asn WHERE status='pending'"),
        "today_inbound": c("SELECT COUNT(*) c FROM wms_inbound_order WHERE status='completed' AND DATE(actual_time)=CURDATE()"),
        "today_outbound": c("SELECT COUNT(*) c FROM wms_outbound_order WHERE status='shipped' AND DATE(actual_time)=CURDATE()"),
        "open_tickets": c("SELECT COUNT(*) c FROM cs_ticket WHERE status IN ('open','processing')"),
    }
    summary = (f"今日运营概览：待处理入库单 {data['pending_inbound']}，待处理出库单 {data['pending_outbound']}，"
               f"待收货 ASN {data['pending_asn']}；今日完成入库 {data['today_inbound']} 单、发货 {data['today_outbound']} 单；"
               f"未关闭客服工单 {data['open_tickets']} 个。")
    return {"ok": True, "title": "运营概览", "summary": summary, "data": data}


def tool_customer(user, slots):
    customer = slots.get("customer")
    if not customer:
        rows = query("""SELECT c.customer_name, COUNT(o.id) total, SUM(o.status='shipped') shipped
                        FROM wms_customer c LEFT JOIN wms_outbound_order o ON o.customer_id=c.id
                        GROUP BY c.id ORDER BY total DESC LIMIT 5""")
        lines = ["请提供客户名称或编码。当前出库量 TOP 客户："] + [f"- {r['customer_name']}：{r['total']} 单（已发货 {r['shipped'] or 0}）" for r in rows]
        return {"ok": True, "title": "客户出库概况", "summary": "\n".join(lines), "data": {"top": rows}}
    orders = query("""SELECT order_no, status, priority, expected_time, actual_time FROM wms_outbound_order
                      WHERE customer_id=%s ORDER BY id DESC LIMIT 8""", (customer["id"],))
    stat = query_one("""SELECT COUNT(*) total, SUM(status='shipped') shipped, SUM(status='cancelled') cancelled
                        FROM wms_outbound_order WHERE customer_id=%s""", (customer["id"],)) or {}
    lines = [f"客户 {customer['customer_name']}：累计出库单 {stat.get('total') or 0}，已发货 {stat.get('shipped') or 0}，已取消 {stat.get('cancelled') or 0}",
             "最近单据：" + "；".join(f"{o['order_no']}({o['status']})" for o in orders[:5]) or "-"]
    return {"ok": True, "title": "客户出库查询", "summary": "\n".join(lines),
            "data": {"customer": customer, "stat": stat, "orders": orders}, "link": "outbound"}


def supplier_scorecard(identifier: str):
    """供应商履约画像：准时率 / 质检合格率 / 供货量 / 近期 ASN"""
    s = None
    if identifier:
        s = match_supplier(identifier)
    if not s:
        return None
    orders = query("""SELECT status, expected_time, actual_time, create_time
                      FROM wms_inbound_order WHERE supplier_id=%s""", (s["id"],))
    total = len(orders)
    completed = sum(1 for o in orders if o["status"] == "completed")
    comparable = [o for o in orders if o["expected_time"] and o["actual_time"]]
    on_time = sum(1 for o in comparable if o["actual_time"] <= o["expected_time"])
    on_time_rate = round(on_time / len(comparable) * 100, 1) if comparable else None

    qc = query_one("""SELECT COALESCE(SUM(i.qualified_qty),0) q, COALESCE(SUM(i.quantity),0) t
                      FROM wms_inspection i JOIN wms_inbound_order o ON i.inbound_id=o.id
                      WHERE o.supplier_id=%s""", (s["id"],)) or {}
    qc_rate = round(float(qc["q"]) / float(qc["t"]) * 100, 1) if qc.get("t") else None

    qty90 = int(query_one("""SELECT COALESCE(SUM(d.received_qty),0) q FROM wms_inbound_detail d
                             JOIN wms_inbound_order o ON d.inbound_id=o.id
                             WHERE o.supplier_id=%s AND o.actual_time>=DATE_SUB(NOW(), INTERVAL 90 DAY)""",
                          (s["id"],))["q"] or 0)
    batches = int(query_one("SELECT COUNT(DISTINCT batch_no) c FROM wms_batch WHERE supplier_id=%s", (s["id"],))["c"] or 0)
    asns = query("""SELECT asn_no, status, expected_time, create_time FROM wms_asn
                    WHERE supplier_id=%s ORDER BY id DESC LIMIT 5""", (s["id"],))
    pending_asn = query_one("SELECT COUNT(*) c FROM wms_asn WHERE supplier_id=%s AND status='pending'", (s["id"],))["c"]

    score = 0.0
    score += 50 * (float(on_time_rate) / 100) if on_time_rate is not None else 25
    score += 50 * (float(qc_rate) / 100) if qc_rate is not None else 25
    score = int(round(score))

    summary = (f"供应商 {s['supplier_name']}（{s['supplier_code']}）履约画像：综合评分 {score} 分；"
               f"到货准时率 {on_time_rate if on_time_rate is not None else '暂无足够数据'}%、"
               f"质检合格率 {qc_rate if qc_rate is not None else '暂无足够数据'}%；"
               f"累计入库单 {total} 单（已完成 {completed}），近 90 天供货 {qty90} 件，"
               f"供货批次 {batches} 个，待收货 ASN {pending_asn} 个。"
               f"对接人：{s['contact'] or '-'} / {s['phone'] or '-'}。")
    return {"ok": True, "title": "供应商履约画像", "summary": summary,
            "data": {"supplier": s, "score": score, "on_time_rate": on_time_rate, "qc_rate": qc_rate,
                     "inbound_total": total, "completed": completed, "qty_90d": qty90,
                     "batches": batches, "recent_asns": asns, "pending_asn": pending_asn},
            "link": "suppliers"}


def tool_supplier(user, slots):
    s = slots.get("supplier") or match_supplier(slots.get("query", ""))
    if not s:
        rows = query("""SELECT s.supplier_name, s.supplier_code, COUNT(o.id) c FROM wms_supplier s
                        LEFT JOIN wms_inbound_order o ON o.supplier_id=s.id
                        WHERE s.status=1 GROUP BY s.id ORDER BY c DESC LIMIT 5""")
        lines = ["未识别到具体供应商，请提供供应商名称或编码。当前供货量 TOP 供应商："]
        lines += [f"- {r['supplier_name']}（{r['supplier_code']}）：{r['c']} 张入库单" for r in rows]
        return {"ok": False, "title": "供应商协同", "summary": "\n".join(lines), "data": {"top": rows}}
    card = supplier_scorecard(s["supplier_code"])
    # 默认供应该供应商的商品
    try:
        products = query("""SELECT sku, product_name, min_stock FROM wms_product
                            WHERE supplier_id=%s AND status=1 ORDER BY id LIMIT 8""", (s["id"],))
    except Exception:
        products = []
    data = card["data"]
    data["products"] = products
    summary = card["summary"]
    if products:
        summary += "\n默认供货商品：" + "、".join(p["product_name"] for p in products)
    return {"ok": True, "title": "供应商协同", "summary": summary, "data": data, "link": "suppliers"}


def tool_supplier_plan(user, slots):
    """按供应商汇总补货需求，生成可直接发给商家的采购沟通清单"""
    rows, live = _pending_replenishments()
    rows = sorted(rows, key=lambda r: (r["supplier_name"] or "", -(r["suggested_qty"] or 0)))
    if not rows:
        return {"ok": True, "title": "供应商补货沟通清单",
                "summary": "当前没有待处理补货建议，无需向供应商发起补货沟通。", "data": {"groups": []}}
    groups = {}
    for r in rows:
        key = r["supplier_code"] or r["supplier_name"]
        g = groups.setdefault(key, {"supplier": r["supplier_name"], "code": r["supplier_code"],
                                    "contact": r["contact"], "phone": r["phone"], "items": [], "total_qty": 0})
        g["items"].append(r)
        g["total_qty"] += r["suggested_qty"] or 0
    lines = [f"{'实时计算' if live else '已生成'}补货需求，按供应商汇总 {len(groups)} 家、{len(rows)} 项："]
    for g in groups.values():
        lines.append(f"- {g['supplier']}（对接人 {g['contact'] or '-'}）：{len(g['items'])} 项，合计 {g['total_qty']} 件")
    lines.append("建议下一步：在「智能补货」确认建议后，通过供应商开放接口创建 ASN，或由采购人员联系商家确认交期。")
    return {"ok": True, "title": "供应商补货沟通清单", "summary": "\n".join(lines), "data": {"groups": list(groups.values())}}


TOOLS = {
    "stock": {"label": "库存查询", "agent": "business", "fn": tool_stock},
    "order": {"label": "单据查询", "agent": "business", "fn": tool_order},
    "alerts": {"label": "预警查询", "agent": "business", "fn": tool_alerts},
    "replenishment": {"label": "补货建议", "agent": "business", "fn": tool_replenishment},
    "locations": {"label": "库容分析", "agent": "business", "fn": tool_locations},
    "expiring": {"label": "效期预警", "agent": "business", "fn": tool_expiring},
    "overview": {"label": "运营概览", "agent": "business", "fn": tool_overview},
    "customer": {"label": "客户查询", "agent": "business", "fn": tool_customer},
    "supplier": {"label": "供应商协同", "agent": "supplier", "fn": tool_supplier},
    "supplier_plan": {"label": "供应商补货清单", "agent": "supplier", "fn": tool_supplier_plan},
}


def run_tool(name, user, slots):
    meta = TOOLS.get(name)
    if not meta:
        return None
    try:
        result = meta["fn"](user, slots)
        result["tool"] = name
        result["agent"] = meta["agent"]
        result["label"] = meta["label"]
        return result
    except Exception as e:
        return {"tool": name, "agent": meta["agent"], "label": meta["label"], "ok": False,
                "title": meta["label"], "summary": f"查询失败：{e}", "data": {}}
