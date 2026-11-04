"""入库管理：收货通知(ASN)/入库单/质检"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from database import query, query_one, execute, execute_return_id, transaction, add_log
from deps import get_current_user, require_perm, ok, fail
from services import confirm_inbound, gen_no, BizError
from datetime import datetime

router = APIRouter(tags=["入库管理"])


class AsnBody(BaseModel):
    warehouse_id: int
    supplier_id: Optional[int] = None
    expected_time: Optional[str] = None
    remark: str = ""
    items: list[dict] = []  # [{product_id, quantity}]


class InboundBody(BaseModel):
    warehouse_id: int
    supplier_id: Optional[int] = None
    asn_id: Optional[int] = None
    expected_time: Optional[str] = None
    remark: str = ""
    items: list[dict] = []  # [{product_id, quantity, batch_no, production_date, expiry_date}]


def _parse_time(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


# ---------- 收货通知 ASN ----------
@router.get("/asn")
def list_asn(status: str = "", user: dict = Depends(get_current_user)):
    where, params = "1=1", []
    if status:
        where += " AND a.status=%s"
        params.append(status)
    rows = query(f"""SELECT a.*, w.warehouse_name, s.supplier_name FROM wms_asn a
                     JOIN wms_warehouse w ON a.warehouse_id=w.id
                     LEFT JOIN wms_supplier s ON a.supplier_id=s.id
                     WHERE {where} ORDER BY a.id DESC""", params)
    for a in rows:
        a["items"] = query("""SELECT d.*, p.sku, p.product_name, p.unit FROM wms_asn_detail d
                              JOIN wms_product p ON d.product_id=p.id WHERE d.asn_id=%s""", (a["id"],))
    return ok(rows)


@router.post("/asn")
def create_asn(body: AsnBody, user: dict = Depends(require_perm("inbound:add"))):
    if not body.items:
        return fail("请添加商品明细")
    try:
        with transaction() as conn:
            asn_no = gen_no(conn, "ASN", "wms_asn", "asn_no")
            aid = execute_return_id(
                """INSERT INTO wms_asn (asn_no, warehouse_id, supplier_id, expected_time, status, remark, operator)
                   VALUES (%s,%s,%s,%s,'pending',%s,%s)""",
                (asn_no, body.warehouse_id, body.supplier_id, _parse_time(body.expected_time), body.remark, user["username"]), conn)
            for it in body.items:
                execute("INSERT INTO wms_asn_detail (asn_id, product_id, quantity) VALUES (%s,%s,%s)",
                        (aid, it["product_id"], it["quantity"]), conn)
            add_log(conn, user, "入库管理", "新建收货通知", f"创建ASN {asn_no}")
        return ok({"id": aid, "asn_no": asn_no}, "收货通知创建成功")
    except BizError as e:
        return fail(e.msg)


@router.post("/asn/{aid}/to-inbound")
def asn_to_inbound(aid: int, user: dict = Depends(require_perm("inbound:add"))):
    """ASN 转入库单（Excel/API 对接模拟）"""
    asn = query_one("SELECT * FROM wms_asn WHERE id=%s", (aid,))
    if not asn:
        return fail("ASN不存在")
    if asn["status"] != "pending":
        return fail("该ASN已处理")
    items = query("SELECT * FROM wms_asn_detail WHERE asn_id=%s", (aid,))
    if not items:
        return fail("ASN无明细")
    try:
        with transaction() as conn:
            order_no = gen_no(conn, "IN", "wms_inbound_order", "order_no")
            oid = execute_return_id(
                """INSERT INTO wms_inbound_order (order_no, warehouse_id, supplier_id, asn_id, status,
                   expected_time, operator) VALUES (%s,%s,%s,%s,'approved',%s,%s)""",
                (order_no, asn["warehouse_id"], asn["supplier_id"], aid, asn["expected_time"], user["username"]), conn)
            for it in items:
                product = query_one("SELECT * FROM wms_product WHERE id=%s", (it["product_id"],), conn)
                batch_no, prod_date, exp_date = "", None, None
                if product["is_batch_managed"]:
                    batch_no = f"B{datetime.now().strftime('%y%m%d')}{it['product_id']:03d}"
                    prod_date = datetime.now().date()
                    if product["shelf_life"]:
                        from datetime import timedelta
                        exp_date = prod_date + timedelta(days=product["shelf_life"])
                execute("""INSERT INTO wms_inbound_detail (inbound_id, product_id, quantity, batch_no,
                           production_date, expiry_date) VALUES (%s,%s,%s,%s,%s,%s)""",
                        (oid, it["product_id"], it["quantity"], batch_no, prod_date, exp_date), conn)
            execute("UPDATE wms_asn SET status='received' WHERE id=%s", (aid,), conn)
            add_log(conn, user, "入库管理", "ASN转入库", f"ASN {asn['asn_no']} 转为入库单 {order_no}")
        return ok({"id": oid, "order_no": order_no}, "已生成入库单")
    except BizError as e:
        return fail(e.msg)


@router.post("/asn/{aid}/cancel")
def cancel_asn(aid: int, user: dict = Depends(require_perm("inbound:add"))):
    execute("UPDATE wms_asn SET status='cancelled' WHERE id=%s AND status='pending'", (aid,))
    add_log(None, user, "入库管理", "取消ASN", f"取消ASN id={aid}")
    return ok(msg="已取消")


# ---------- 入库单 ----------
@router.get("/inbound-orders")
def list_inbound(status: str = "", warehouse_id: Optional[int] = None, keyword: str = "",
                 page: int = 1, size: int = 10, user: dict = Depends(get_current_user)):
    where, params = "1=1", []
    if status:
        where += " AND o.status=%s"
        params.append(status)
    if warehouse_id:
        where += " AND o.warehouse_id=%s"
        params.append(warehouse_id)
    if keyword:
        where += " AND (o.order_no LIKE %s OR s.supplier_name LIKE %s)"
        params += [f"%{keyword}%"] * 2
    total = query_one(f"""SELECT COUNT(*) c FROM wms_inbound_order o LEFT JOIN wms_supplier s ON o.supplier_id=s.id
                          WHERE {where}""", params)["c"]
    rows = query(f"""SELECT o.*, w.warehouse_name, s.supplier_name FROM wms_inbound_order o
                     JOIN wms_warehouse w ON o.warehouse_id=w.id
                     LEFT JOIN wms_supplier s ON o.supplier_id=s.id
                     WHERE {where} ORDER BY o.id DESC LIMIT %s OFFSET %s""",
                 params + [size, (page - 1) * size])
    return ok({"total": total, "list": rows})


@router.get("/inbound-orders/{oid}")
def get_inbound(oid: int, user: dict = Depends(get_current_user)):
    order = query_one("""SELECT o.*, w.warehouse_name, s.supplier_name FROM wms_inbound_order o
                         JOIN wms_warehouse w ON o.warehouse_id=w.id
                         LEFT JOIN wms_supplier s ON o.supplier_id=s.id WHERE o.id=%s""", (oid,))
    if not order:
        return fail("入库单不存在")
    order["details"] = query("""SELECT d.*, p.sku, p.product_name, p.unit, p.price, l.location_code
                                FROM wms_inbound_detail d
                                JOIN wms_product p ON d.product_id=p.id
                                LEFT JOIN wms_location l ON d.location_id=l.id
                                WHERE d.inbound_id=%s""", (oid,))
    return ok(order)


@router.post("/inbound-orders")
def create_inbound(body: InboundBody, user: dict = Depends(require_perm("inbound:add"))):
    if not body.items:
        return fail("请添加商品明细")
    try:
        with transaction() as conn:
            order_no = gen_no(conn, "IN", "wms_inbound_order", "order_no")
            oid = execute_return_id(
                """INSERT INTO wms_inbound_order (order_no, warehouse_id, supplier_id, asn_id, status,
                   expected_time, operator, remark) VALUES (%s,%s,%s,%s,'pending',%s,%s,%s)""",
                (order_no, body.warehouse_id, body.supplier_id, body.asn_id, _parse_time(body.expected_time),
                 user["username"], body.remark), conn)
            for it in body.items:
                execute("""INSERT INTO wms_inbound_detail (inbound_id, product_id, quantity, batch_no,
                           production_date, expiry_date) VALUES (%s,%s,%s,%s,%s,%s)""",
                        (oid, it["product_id"], it["quantity"], it.get("batch_no") or "",
                         _parse_time(it.get("production_date")), _parse_time(it.get("expiry_date"))), conn)
            add_log(conn, user, "入库管理", "创建入库单", f"创建入库单 {order_no}")
        return ok({"id": oid, "order_no": order_no}, "入库单创建成功")
    except BizError as e:
        return fail(e.msg)


@router.put("/inbound-orders/{oid}")
def update_inbound(oid: int, body: InboundBody, user: dict = Depends(require_perm("inbound:add"))):
    order = query_one("SELECT * FROM wms_inbound_order WHERE id=%s", (oid,))
    if not order:
        return fail("入库单不存在")
    if order["status"] != "pending":
        return fail("仅待审核状态可编辑")
    try:
        with transaction() as conn:
            execute("""UPDATE wms_inbound_order SET warehouse_id=%s, supplier_id=%s, expected_time=%s, remark=%s
                       WHERE id=%s""",
                    (body.warehouse_id, body.supplier_id, _parse_time(body.expected_time), body.remark, oid), conn)
            execute("DELETE FROM wms_inbound_detail WHERE inbound_id=%s", (oid,), conn)
            for it in body.items:
                execute("""INSERT INTO wms_inbound_detail (inbound_id, product_id, quantity, batch_no,
                           production_date, expiry_date) VALUES (%s,%s,%s,%s,%s,%s)""",
                        (oid, it["product_id"], it["quantity"], it.get("batch_no") or "",
                         _parse_time(it.get("production_date")), _parse_time(it.get("expiry_date"))), conn)
            add_log(conn, user, "入库管理", "修改入库单", f"修改入库单 {order['order_no']}")
        return ok(msg="更新成功")
    except BizError as e:
        return fail(e.msg)


@router.post("/inbound-orders/{oid}/approve")
def approve_inbound(oid: int, user: dict = Depends(require_perm("inbound:audit"))):
    row = execute("UPDATE wms_inbound_order SET status='approved' WHERE id=%s AND status='pending'", (oid,))
    if not row:
        return fail("仅待审核状态可审核")
    add_log(None, user, "入库管理", "审核", f"入库单 id={oid} 审核通过")
    return ok(msg="审核通过")


@router.post("/inbound-orders/{oid}/confirm")
def confirm_inbound_api(oid: int, body: dict = None, user: dict = Depends(require_perm("inbound:confirm"))):
    """确认入库：联动库存/批次/库位/移库记录/质检。body: {inspections: {detail_id: {qualified_qty, unqualified_qty}}}"""
    try:
        with transaction() as conn:
            result = confirm_inbound(conn, oid, user, (body or {}).get("inspections"))
        return ok(result, "入库完成，库存已更新")
    except BizError as e:
        return fail(e.msg)


@router.post("/inbound-orders/{oid}/cancel")
def cancel_inbound(oid: int, user: dict = Depends(require_perm("inbound:audit"))):
    row = execute("UPDATE wms_inbound_order SET status='cancelled' WHERE id=%s AND status IN ('pending','approved')", (oid,))
    if not row:
        return fail("当前状态不可取消")
    add_log(None, user, "入库管理", "取消", f"取消入库单 id={oid}")
    return ok(msg="已取消")


# ---------- 质检 ----------
@router.get("/inspections")
def list_inspections(user: dict = Depends(require_perm("inbound:view"))):
    rows = query("""SELECT i.*, p.sku, p.product_name, o.order_no FROM wms_inspection i
                    JOIN wms_product p ON i.product_id=p.id
                    LEFT JOIN wms_inbound_order o ON i.inbound_id=o.id ORDER BY i.id DESC LIMIT 200""")
    return ok(rows)
