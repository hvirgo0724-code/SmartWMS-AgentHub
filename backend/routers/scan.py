"""扫码作业：条码/库位/单据识别、快捷移库、扫码入库发货与扫码日志"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from datetime import datetime

from database import query, query_one, execute, execute_return_id, transaction, add_log
from deps import get_current_user, require_perm, ok, fail
from services import (gen_no, confirm_inbound, allocate_outbound, ship_outbound,
                      add_stock_move, upsert_inventory, BizError)

router = APIRouter(tags=["扫码作业"])


class ScanMoveBody(BaseModel):
    from_code: str
    product_code: str
    to_code: str
    quantity: int


class ScanPickBody(BaseModel):
    order_no: str


def _perm(user, code):
    perms = user.get("perms", [])
    return "*" in perms or code in perms


def _clean(code: str) -> str:
    return (code or "").strip()


def _log(user, code, scan_type, ref_id=None, ref_no="", action="scan", result="success"):
    try:
        execute_return_id("""INSERT INTO wms_scan_log
            (code, scan_type, ref_id, ref_no, action, result, operator)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (code[:120], scan_type, ref_id, (ref_no or "")[:80], action, result, user.get("username", "")))
    except Exception as e:
        print(f"[scan] 日志写入失败: {e}")


def _find_product(code: str):
    return query_one("""SELECT * FROM wms_product WHERE status=1
                        AND (barcode=%s OR UPPER(sku)=UPPER(%s)) LIMIT 1""", (code, code))


def _find_location(code: str):
    return query_one("""SELECT l.*, a.area_code, a.area_name, w.warehouse_name, w.warehouse_code
                        FROM wms_location l JOIN wms_area a ON l.area_id=a.id
                        JOIN wms_warehouse w ON a.warehouse_id=w.id
                        WHERE UPPER(l.location_code)=UPPER(%s) LIMIT 1""", (code,))


def _product_payload(p):
    stock = query_one("""SELECT COALESCE(SUM(quantity),0) qty, COALESCE(SUM(available_qty),0) avail,
                                COUNT(DISTINCT location_id) locs
                         FROM wms_inventory WHERE product_id=%s""", (p["id"],))
    rows = query("""SELECT w.warehouse_name, l.location_code, i.batch_no, i.quantity, i.available_qty,
                           i.status
                    FROM wms_inventory i JOIN wms_location l ON i.location_id=l.id
                    JOIN wms_warehouse w ON i.warehouse_id=w.id
                    WHERE i.product_id=%s AND i.quantity>0 ORDER BY i.quantity DESC LIMIT 8""", (p["id"],))
    return {
        "type": "product", "title": p["product_name"], "subtitle": f"SKU {p['sku']} · 条码 {p['barcode'] or '-'}",
        "badge": "商品", "data": {
            "product": p, "stock": stock, "locations": rows,
            "min_stock": p["min_stock"], "max_stock": p["max_stock"], "unit": p["unit"],
        },
    }


def _location_payload(l):
    items = query("""SELECT p.sku, p.product_name, p.unit, i.batch_no, i.quantity, i.locked_qty,
                            i.available_qty, i.status
                     FROM wms_inventory i JOIN wms_product p ON i.product_id=p.id
                     WHERE i.location_id=%s AND i.quantity>0 ORDER BY p.sku""", (l["id"],))
    return {
        "type": "location", "title": l["location_code"], "subtitle": f"{l['warehouse_name']} · {l['area_name']}",
        "badge": "库位", "data": {"location": l, "items": items},
    }


def _inbound_payload(o, user):
    details = query("""SELECT d.*, p.sku, p.product_name, p.unit FROM wms_inbound_detail d
                       JOIN wms_product p ON d.product_id=p.id WHERE d.inbound_id=%s""", (o["id"],))
    can_confirm = o["status"] in ("pending", "approved") and _perm(user, "inbound:confirm")
    return {
        "type": "inbound", "title": o["order_no"], "subtitle": f"{o.get('warehouse_name','')} · 供应商 {o.get('supplier_name') or '-'}",
        "badge": "入库单", "data": {"order": o, "details": details},
        "actions": [{
            "key": "confirm_inbound", "label": "一键确认入库", "enabled": bool(can_confirm),
            "reason": "" if can_confirm else ("状态不可入库" if o["status"] not in ("pending", "approved") else "无入库确认权限"),
        }],
    }


def _outbound_payload(o, user):
    details = query("""SELECT d.*, p.sku, p.product_name, p.unit FROM wms_outbound_detail d
                       JOIN wms_product p ON d.product_id=p.id WHERE d.outbound_id=%s""", (o["id"],))
    can_ship = o["status"] in ("approved", "allocated", "picked") and _perm(user, "outbound:ship")
    if o["status"] == "approved" and not _perm(user, "outbound:allocate"):
        can_ship = False
    return {
        "type": "outbound", "title": o["order_no"], "subtitle": f"{o.get('warehouse_name','')} · 客户 {o.get('customer_name') or '-'}",
        "badge": "出库单", "data": {"order": o, "details": details},
        "actions": [{
            "key": "ship_outbound", "label": "分配并发货", "enabled": bool(can_ship),
            "reason": "" if can_ship else ("状态不可发货" if o["status"] not in ("approved", "allocated", "picked") else "无出库分配/发货权限"),
        }],
    }


def _asn_payload(a, user):
    items = query("""SELECT d.quantity, p.sku, p.product_name, p.unit FROM wms_asn_detail d
                     JOIN wms_product p ON d.product_id=p.id WHERE d.asn_id=%s""", (a["id"],))
    return {
        "type": "asn", "title": a["asn_no"], "subtitle": f"供应商 {a.get('supplier_name') or '-'}",
        "badge": "收货通知", "data": {"asn": a, "items": items},
        "actions": [{
            "key": "asn_to_inbound", "label": "转入库单", "enabled": a["status"] == "pending" and _perm(user, "inbound:add"),
            "reason": "" if a["status"] == "pending" else "该 ASN 已处理",
        }],
    }


def _wave_payload(w, user):
    list_data = query("""SELECT d.product_id, p.sku, p.product_name, SUM(d.quantity) qty
                         FROM wms_outbound_detail d JOIN wms_outbound_order o ON d.outbound_id=o.id
                         JOIN wms_product p ON d.product_id=p.id
                         WHERE o.wave_id=%s GROUP BY d.product_id, p.sku, p.product_name""", (w["id"],))
    return {
        "type": "wave", "title": w["wave_no"], "subtitle": f"波次 · {w['order_count']} 个订单",
        "badge": "波次", "data": {"wave": w, "items": list_data},
        "actions": [{
            "key": "wave_pick", "label": "一键拣货发货",
            "enabled": w["status"] == "pending" and _perm(user, "outbound:allocate"),
            "reason": "" if w["status"] == "pending" else "波次已处理",
        }],
    }


@router.get("/scan/tasks")
def scan_tasks(user: dict = Depends(require_perm("scan:view"))):
    def count(sql):
        return query_one(sql)["c"]
    counts = {
        "inbound": count("SELECT COUNT(*) c FROM wms_inbound_order WHERE status IN ('pending','approved')"),
        "outbound": count("SELECT COUNT(*) c FROM wms_outbound_order WHERE status IN ('approved','allocated')"),
        "asn": count("SELECT COUNT(*) c FROM wms_asn WHERE status='pending'"),
        "wave": count("SELECT COUNT(*) c FROM wms_wave WHERE status='pending'"),
    }
    recent = query("""SELECT order_no, status, create_time FROM wms_inbound_order
                      WHERE status IN ('pending','approved') ORDER BY id DESC LIMIT 3""")
    outbound = query("""SELECT order_no, status, create_time FROM wms_outbound_order
                        WHERE status IN ('approved','allocated') ORDER BY id DESC LIMIT 3""")
    return ok({"counts": counts, "inbound": recent, "outbound": outbound})


@router.get("/scan/resolve")
def scan_resolve(code: str = "", user: dict = Depends(require_perm("scan:view"))):
    """通用扫码解析：商品条码/SKU、库位编码、入库单、出库单、ASN、波次"""
    code = _clean(code)
    if not code:
        return fail("请扫描或输入编码")
    p = _find_product(code)
    if p:
        _log(user, code, "product", p["id"], p["sku"], "resolve")
        return ok(_product_payload(p))
    loc = _find_location(code)
    if loc:
        _log(user, code, "location", loc["id"], loc["location_code"], "resolve")
        result = _location_payload(loc)
        result["actions"] = [{
            "key": "move", "label": "以该库位发起移库",
            "enabled": _perm(user, "inventory:move"), "reason": "" if _perm(user, "inventory:move") else "无移库权限",
        }]
        return ok(result)
    up = code.upper()
    if up.startswith("IN"):
        o = query_one("""SELECT o.*, w.warehouse_name, s.supplier_name FROM wms_inbound_order o
                         JOIN wms_warehouse w ON o.warehouse_id=w.id
                         LEFT JOIN wms_supplier s ON o.supplier_id=s.id WHERE o.order_no=%s""", (up,))
        if o:
            _log(user, code, "inbound", o["id"], o["order_no"], "resolve")
            return ok(_inbound_payload(o, user))
    if up.startswith("OUT"):
        o = query_one("""SELECT o.*, w.warehouse_name, c.customer_name FROM wms_outbound_order o
                         JOIN wms_warehouse w ON o.warehouse_id=w.id
                         LEFT JOIN wms_customer c ON o.customer_id=c.id WHERE o.order_no=%s""", (up,))
        if o:
            _log(user, code, "outbound", o["id"], o["order_no"], "resolve")
            return ok(_outbound_payload(o, user))
    if up.startswith("ASN"):
        a = query_one("""SELECT a.*, w.warehouse_name, s.supplier_name FROM wms_asn a
                         JOIN wms_warehouse w ON a.warehouse_id=w.id
                         LEFT JOIN wms_supplier s ON a.supplier_id=s.id WHERE a.asn_no=%s""", (up,))
        if a:
            _log(user, code, "asn", a["id"], a["asn_no"], "resolve")
            return ok(_asn_payload(a, user))
    if up.startswith("WAVE"):
        w = query_one("SELECT * FROM wms_wave WHERE wave_no=%s", (up,))
        if w:
            _log(user, code, "wave", w["id"], w["wave_no"], "resolve")
            return ok(_wave_payload(w, user))
    _log(user, code, "unknown", None, "", "resolve", "not_found")
    return fail(f"未识别编码 {code}，请确认条码/库位/单据号")


@router.get("/scan/logs")
def scan_logs(limit: int = 12, user: dict = Depends(require_perm("scan:view"))):
    rows = query("""SELECT * FROM wms_scan_log WHERE operator=%s
                    ORDER BY id DESC LIMIT %s""", (user["username"], min(limit, 50)))
    return ok(rows)


@router.post("/scan/move")
def scan_move(body: ScanMoveBody, user: dict = Depends(require_perm("inventory:move"))):
    """扫码移库：源库位码 + 商品条码/SKU + 目标库位码 + 数量"""
    src = _find_location(_clean(body.from_code))
    dst = _find_location(_clean(body.to_code))
    product = _find_product(_clean(body.product_code))
    if not src:
        return fail("源库位不存在")
    if not dst:
        return fail("目标库位不存在")
    if not product:
        return fail("商品不存在")
    if body.quantity <= 0:
        return fail("数量必须大于 0")
    if src["id"] == dst["id"]:
        return fail("源库位与目标库位相同")
    if dst["status"] == "locked":
        return fail("目标库位已锁定")
    inv = query_one("""SELECT * FROM wms_inventory WHERE location_id=%s AND product_id=%s
                       AND quantity>0 AND status='normal' ORDER BY batch_no, id LIMIT 1""",
                    (src["id"], product["id"]))
    if not inv:
        return fail("源库位没有该商品库存")
    if body.quantity > inv["available_qty"]:
        return fail(f"可移动数量不足（可用 {inv['available_qty']}）")
    try:
        with transaction() as conn:
            remain = inv["quantity"] - body.quantity
            if remain > 0:
                execute("""UPDATE wms_inventory SET quantity=quantity-%s, available_qty=available_qty-%s
                           WHERE id=%s""", (body.quantity, body.quantity, inv["id"]), conn)
            else:
                if inv["locked_qty"] > 0:
                    raise BizError("该批次存在锁定库存，不能全部移出")
                execute("DELETE FROM wms_inventory WHERE id=%s", (inv["id"],), conn)
            upsert_inventory(conn, inv["warehouse_id"], dst["id"], inv["product_id"], inv["batch_no"], body.quantity)
            execute("UPDATE wms_location SET status='occupied' WHERE id=%s AND status='empty'", (dst["id"],), conn)
            remain_cnt = query_one("SELECT COUNT(*) c FROM wms_inventory WHERE location_id=%s AND quantity>0",
                                   (src["id"],), conn)["c"]
            execute(f"UPDATE wms_location SET status='{'occupied' if remain_cnt else 'empty'}' WHERE id=%s",
                    (src["id"],), conn)
            add_stock_move(conn, "move", inv["warehouse_id"], src["id"], dst["id"], inv["product_id"],
                           inv["batch_no"], body.quantity, "scan", "SCAN-MOVE", user["username"])
            add_log(conn, user, "扫码作业", "扫码移库",
                    f"{product['sku']} {body.quantity}件 {src['location_code']}→{dst['location_code']}")
        _log(user, f"{body.from_code}/{body.product_code}/{body.to_code}", "move", inv["product_id"],
             product["sku"], "move")
        return ok({"sku": product["sku"], "quantity": body.quantity,
                   "from": src["location_code"], "to": dst["location_code"]}, "移库成功")
    except BizError as e:
        return fail(e.msg)


@router.post("/scan/inbound/{oid}/confirm")
def scan_confirm_inbound(oid: int, user: dict = Depends(require_perm("inbound:confirm"))):
    order = query_one("SELECT * FROM wms_inbound_order WHERE id=%s", (oid,))
    if not order:
        return fail("入库单不存在")
    try:
        with transaction() as conn:
            confirm_inbound(conn, oid, user)
        _log(user, order["order_no"], "inbound", oid, order["order_no"], "confirm")
        return ok({"order_no": order["order_no"]}, "扫码入库完成")
    except BizError as e:
        return fail(e.msg)


@router.post("/scan/outbound/{oid}/ship")
def scan_ship_outbound(oid: int, user: dict = Depends(require_perm("outbound:ship"))):
    order = query_one("SELECT * FROM wms_outbound_order WHERE id=%s", (oid,))
    if not order:
        return fail("出库单不存在")
    if not _perm(user, "outbound:allocate"):
        return fail("无出库分配权限，无法执行扫码发货")
    try:
        with transaction() as conn:
            if order["status"] == "approved":
                allocate_outbound(conn, oid, user)
            ship_outbound(conn, oid, user)
        _log(user, order["order_no"], "outbound", oid, order["order_no"], "ship")
        return ok({"order_no": order["order_no"]}, "扫码发货完成")
    except BizError as e:
        return fail(e.msg)


@router.post("/scan/asn/{aid}/to-inbound")
def scan_asn_to_inbound(aid: int, user: dict = Depends(require_perm("inbound:add"))):
    asn = query_one("SELECT * FROM wms_asn WHERE id=%s", (aid,))
    if not asn:
        return fail("ASN 不存在")
    if asn["status"] != "pending":
        return fail("该 ASN 已处理")
    items = query("SELECT * FROM wms_asn_detail WHERE asn_id=%s", (aid,))
    if not items:
        return fail("ASN 无明细")
    try:
        from datetime import timedelta
        with transaction() as conn:
            order_no = gen_no(conn, "IN", "wms_inbound_order", "order_no")
            oid = execute_return_id("""INSERT INTO wms_inbound_order
                (order_no, warehouse_id, supplier_id, asn_id, status, expected_time, operator)
                VALUES (%s,%s,%s,%s,'approved',%s,%s)""",
                (order_no, asn["warehouse_id"], asn["supplier_id"], aid, asn["expected_time"], user["username"]), conn)
            for it in items:
                product = query_one("SELECT * FROM wms_product WHERE id=%s", (it["product_id"],), conn)
                batch_no, prod_date, exp_date = "", None, None
                if product["is_batch_managed"]:
                    batch_no = f"B{datetime.now().strftime('%y%m%d')}{it['product_id']:03d}"
                    prod_date = datetime.now().date()
                    if product["shelf_life"]:
                        exp_date = prod_date + timedelta(days=product["shelf_life"])
                execute("""INSERT INTO wms_inbound_detail (inbound_id, product_id, quantity, batch_no,
                           production_date, expiry_date) VALUES (%s,%s,%s,%s,%s,%s)""",
                        (oid, it["product_id"], it["quantity"], batch_no, prod_date, exp_date), conn)
            execute("UPDATE wms_asn SET status='received' WHERE id=%s", (aid,), conn)
            add_log(conn, user, "扫码作业", "ASN转入库", f"{asn['asn_no']} → {order_no}")
        _log(user, asn["asn_no"], "asn", aid, asn["asn_no"], "to_inbound")
        return ok({"id": oid, "order_no": order_no}, "已生成入库单")
    except BizError as e:
        return fail(e.msg)


@router.post("/scan/wave/{wid}/pick")
def scan_wave_pick(wid: int, user: dict = Depends(require_perm("outbound:allocate"))):
    wave = query_one("SELECT * FROM wms_wave WHERE id=%s", (wid,))
    if not wave:
        return fail("波次不存在")
    if wave["status"] != "pending":
        return fail("波次已处理")
    orders = query("SELECT * FROM wms_outbound_order WHERE wave_id=%s AND status IN ('approved','allocated')", (wid,))
    if not orders:
        return fail("波次内无可拣货订单")
    try:
        with transaction() as conn:
            count = 0
            for o in orders:
                if o["status"] == "approved":
                    allocate_outbound(conn, o["id"], user)
                ship_outbound(conn, o["id"], user)
                count += 1
            execute("UPDATE wms_wave SET status='picked' WHERE id=%s", (wid,), conn)
            add_log(conn, user, "扫码作业", "波次拣货", f"{wave['wave_no']} 完成 {count} 单")
        _log(user, wave["wave_no"], "wave", wid, wave["wave_no"], "pick")
        return ok({"picked": count}, f"已拣货发货 {count} 单")
    except BizError as e:
        return fail(e.msg)
