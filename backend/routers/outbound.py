"""出库管理：出库单/波次拣货/发货"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from database import query, query_one, execute, execute_return_id, transaction, add_log
from deps import get_current_user, require_perm, ok, fail
from services import allocate_outbound, ship_outbound, release_outbound, gen_no, BizError
from datetime import datetime

router = APIRouter(tags=["出库管理"])


class OutboundBody(BaseModel):
    warehouse_id: int
    customer_id: Optional[int] = None
    priority: int = 2
    expected_time: Optional[str] = None
    remark: str = ""
    items: list[dict] = []  # [{product_id, quantity}]


def _parse_time(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


@router.get("/outbound-orders")
def list_outbound(status: str = "", warehouse_id: Optional[int] = None, keyword: str = "",
                  page: int = 1, size: int = 10, user: dict = Depends(get_current_user)):
    where, params = "1=1", []
    if status:
        where += " AND o.status=%s"
        params.append(status)
    if warehouse_id:
        where += " AND o.warehouse_id=%s"
        params.append(warehouse_id)
    if keyword:
        where += " AND (o.order_no LIKE %s OR c.customer_name LIKE %s)"
        params += [f"%{keyword}%"] * 2
    total = query_one(f"""SELECT COUNT(*) c FROM wms_outbound_order o LEFT JOIN wms_customer c ON o.customer_id=c.id
                          WHERE {where}""", params)["c"]
    rows = query(f"""SELECT o.*, w.warehouse_name, c.customer_name, v.wave_no FROM wms_outbound_order o
                     JOIN wms_warehouse w ON o.warehouse_id=w.id
                     LEFT JOIN wms_customer c ON o.customer_id=c.id
                     LEFT JOIN wms_wave v ON o.wave_id=v.id
                     WHERE {where} ORDER BY o.id DESC LIMIT %s OFFSET %s""",
                 params + [size, (page - 1) * size])
    return ok({"total": total, "list": rows})


@router.get("/outbound-orders/{oid}")
def get_outbound(oid: int, user: dict = Depends(get_current_user)):
    order = query_one("""SELECT o.*, w.warehouse_name, c.customer_name, v.wave_no FROM wms_outbound_order o
                         JOIN wms_warehouse w ON o.warehouse_id=w.id
                         LEFT JOIN wms_customer c ON o.customer_id=c.id
                         LEFT JOIN wms_wave v ON o.wave_id=v.id WHERE o.id=%s""", (oid,))
    if not order:
        return fail("出库单不存在")
    order["details"] = query("""SELECT d.*, p.sku, p.product_name, p.unit, p.price, l.location_code
                                FROM wms_outbound_detail d
                                JOIN wms_product p ON d.product_id=p.id
                                LEFT JOIN wms_location l ON d.location_id=l.id
                                WHERE d.outbound_id=%s""", (oid,))
    order["allocations"] = query("""SELECT a.*, p.sku, p.product_name, l.location_code FROM wms_allocation a
                                    JOIN wms_product p ON a.product_id=p.id
                                    JOIN wms_location l ON a.location_id=l.id
                                    WHERE a.outbound_id=%s""", (oid,))
    return ok(order)


@router.post("/outbound-orders")
def create_outbound(body: OutboundBody, user: dict = Depends(require_perm("outbound:add"))):
    if not body.items:
        return fail("请添加商品明细")
    # 库存预检查
    for it in body.items:
        avail = query_one("""SELECT COALESCE(SUM(available_qty),0) a FROM wms_inventory
                             WHERE warehouse_id=%s AND product_id=%s AND status='normal'""",
                          (body.warehouse_id, it["product_id"]))["a"]
        if avail < it["quantity"]:
            p = query_one("SELECT sku FROM wms_product WHERE id=%s", (it["product_id"],))
            return fail(f"商品 {p['sku']} 当前可用库存不足（可用 {avail}）")
    try:
        with transaction() as conn:
            order_no = gen_no(conn, "OUT", "wms_outbound_order", "order_no")
            oid = execute_return_id(
                """INSERT INTO wms_outbound_order (order_no, warehouse_id, customer_id, priority, status,
                   expected_time, operator, remark) VALUES (%s,%s,%s,%s,'pending',%s,%s,%s)""",
                (order_no, body.warehouse_id, body.customer_id, body.priority, _parse_time(body.expected_time),
                 user["username"], body.remark), conn)
            for it in body.items:
                execute("INSERT INTO wms_outbound_detail (outbound_id, product_id, quantity) VALUES (%s,%s,%s)",
                        (oid, it["product_id"], it["quantity"]), conn)
            add_log(conn, user, "出库管理", "创建出库单", f"创建出库单 {order_no}")
        return ok({"id": oid, "order_no": order_no}, "出库单创建成功")
    except BizError as e:
        return fail(e.msg)


@router.post("/outbound-orders/{oid}/approve")
def approve_outbound(oid: int, user: dict = Depends(require_perm("outbound:audit"))):
    row = execute("UPDATE wms_outbound_order SET status='approved' WHERE id=%s AND status='pending'", (oid,))
    if not row:
        return fail("仅待审核状态可审核")
    add_log(None, user, "出库管理", "审核", f"出库单 id={oid} 审核通过")
    return ok(msg="审核通过")


@router.post("/outbound-orders/{oid}/allocate")
def allocate_api(oid: int, user: dict = Depends(require_perm("outbound:allocate"))):
    """分配库存（FIFO 锁定）"""
    try:
        with transaction() as conn:
            result = allocate_outbound(conn, oid, user)
        return ok(result, "库存已按先进先出分配并锁定")
    except BizError as e:
        return fail(e.msg)


@router.post("/outbound-orders/{oid}/ship")
def ship_api(oid: int, user: dict = Depends(require_perm("outbound:ship"))):
    """发货确认（扣减库存、释放库位、生成发货记录）"""
    try:
        with transaction() as conn:
            result = ship_outbound(conn, oid, user)
        return ok(result, "发货成功，库存已扣减")
    except BizError as e:
        return fail(e.msg)


@router.post("/outbound-orders/{oid}/cancel")
def cancel_outbound(oid: int, user: dict = Depends(require_perm("outbound:audit"))):
    order = query_one("SELECT * FROM wms_outbound_order WHERE id=%s", (oid,))
    if not order:
        return fail("出库单不存在")
    if order["status"] == "shipped":
        return fail("已发货订单不可取消")
    if order["status"] == "cancelled":
        return fail("订单已取消")
    try:
        with transaction() as conn:
            release_outbound(conn, oid, user)
            execute("UPDATE wms_outbound_order SET status='cancelled' WHERE id=%s", (oid,), conn)
            add_log(conn, user, "出库管理", "取消", f"取消出库单 {order['order_no']}，锁定库存已释放")
        return ok(msg="已取消，锁定库存已释放")
    except BizError as e:
        return fail(e.msg)


# ---------- 波次拣货 ----------
class WaveBody(BaseModel):
    warehouse_id: int
    strategy: str = "order"
    order_ids: list[int] = []


@router.get("/waves")
def list_waves(user: dict = Depends(get_current_user)):
    rows = query("""SELECT v.*, w.warehouse_name FROM wms_wave v
                    JOIN wms_warehouse w ON v.warehouse_id=w.id ORDER BY v.id DESC""")
    for v in rows:
        v["orders"] = query("""SELECT o.id, o.order_no, o.status, c.customer_name FROM wms_outbound_order o
                               LEFT JOIN wms_customer c ON o.customer_id=c.id WHERE o.wave_id=%s""", (v["id"],))
    return ok(rows)


@router.post("/waves")
def create_wave(body: WaveBody, user: dict = Depends(require_perm("outbound:allocate"))):
    if not body.order_ids:
        return fail("请选择出库单")
    orders = query("SELECT * FROM wms_outbound_order WHERE id IN (%s)" % ",".join(map(str, body.order_ids)))
    for o in orders:
        if o["status"] != "approved":
            return fail(f"出库单 {o['order_no']} 状态为 {o['status']}，需为已审核状态")
    try:
        with transaction() as conn:
            wave_no = gen_no(conn, "WV", "wms_wave", "wave_no")
            vid = execute_return_id("INSERT INTO wms_wave (wave_no, warehouse_id, strategy, status, order_count, operator) VALUES (%s,%s,%s,'pending',%s,%s)",
                          (wave_no, body.warehouse_id, body.strategy, len(body.order_ids), user["username"]), conn)
            execute("UPDATE wms_outbound_order SET wave_id=%s WHERE id IN (" +
                    ",".join(["%s"] * len(body.order_ids)) + ")",
                    (vid, *body.order_ids), conn)
            add_log(conn, user, "出库管理", "创建波次", f"创建波次 {wave_no}，包含 {len(body.order_ids)} 个订单")
        return ok({"id": vid, "wave_no": wave_no}, "波次创建成功")
    except BizError as e:
        return fail(e.msg)


@router.get("/waves/{vid}/pick-list")
def wave_pick_list(vid: int, user: dict = Depends(get_current_user)):
    """播种式拣货单：按商品汇总波次内全部订单需求"""
    wave = query_one("SELECT * FROM wms_wave WHERE id=%s", (vid,))
    if not wave:
        return fail("波次不存在")
    items = query("""SELECT a.product_id, p.sku, p.product_name, l.location_code, a.batch_no, SUM(a.quantity) total_qty,
                     COUNT(DISTINCT a.outbound_id) order_count
                     FROM wms_allocation a
                     JOIN wms_outbound_order o ON a.outbound_id=o.id
                     JOIN wms_product p ON a.product_id=p.id
                     JOIN wms_location l ON a.location_id=l.id
                     WHERE o.wave_id=%s GROUP BY a.product_id, l.location_code, a.batch_no
                     ORDER BY p.sku""", (vid,))
    if not items:  # 未分配则按订单明细汇总
        items = query("""SELECT d.product_id, p.sku, p.product_name, SUM(d.quantity) total_qty, 0 order_count, '' location_code, '' batch_no
                         FROM wms_outbound_detail d JOIN wms_outbound_order o ON d.outbound_id=o.id
                         JOIN wms_product p ON d.product_id=p.id
                         WHERE o.wave_id=%s GROUP BY d.product_id ORDER BY p.sku""", (vid,))
    return ok({"wave": wave, "items": items})


@router.post("/waves/{vid}/pick")
def wave_pick(vid: int, user: dict = Depends(require_perm("outbound:allocate"))):
    """波次拣货完成：对波次内所有订单自动分配并拣货发货"""
    wave = query_one("SELECT * FROM wms_wave WHERE id=%s", (vid,))
    if not wave:
        return fail("波次不存在")
    if wave["status"] != "pending":
        return fail("波次已完成或取消")
    orders = query("SELECT * FROM wms_outbound_order WHERE wave_id=%s AND status IN ('approved','allocated')", (vid,))
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
            execute("UPDATE wms_wave SET status='picked' WHERE id=%s", (vid,), conn)
            add_log(conn, user, "出库管理", "波次拣货", f"波次 {wave['wave_no']} 完成 {count} 单拣货发货")
        return ok({"picked": count}, f"波次拣货完成，共发货 {count} 单")
    except BizError as e:
        return fail(e.msg)
