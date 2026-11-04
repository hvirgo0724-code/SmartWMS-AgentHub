"""核心业务服务：入库上架/出库分配发货/库存联动（供路由与数据初始化共用）"""
from database import query, query_one, execute, execute_return_id, add_log
from datetime import datetime, date


class BizError(Exception):
    """业务异常，事务回滚并返回给前端"""
    def __init__(self, msg):
        self.msg = msg


def gen_no(conn, prefix, table, col):
    """生成业务单号: IN20260825001"""
    today = date.today().strftime("%Y%m%d")
    like = f"{prefix}{today}%"
    row = query_one(f"SELECT {col} FROM {table} WHERE {col} LIKE %s ORDER BY {col} DESC LIMIT 1", (like,), conn)
    seq = 1
    if row:
        seq = int(str(row[col])[-3:]) + 1
    return f"{prefix}{today}{seq:03d}"


# ---------- 库位智能推荐 ----------
def recommend_location(conn, warehouse_id, product):
    """上架策略：优先同类商品已有存放且未满的库位 -> 空闲存储区库位 -> 任意空闲库位"""
    # 1. 已存放同商品的库位
    loc = query_one("""
        SELECT l.* FROM wms_location l
        JOIN wms_area a ON l.area_id=a.id
        JOIN wms_inventory i ON i.location_id=l.id
        WHERE a.warehouse_id=%s AND i.product_id=%s AND i.quantity>0
        ORDER BY i.quantity DESC LIMIT 1""", (warehouse_id, product["id"]), conn)
    if loc:
        return loc["id"]
    # 2. 温控商品优先温控库位，普通商品优先普通库位（存储区）
    want_type = "temp" if (product.get("category") in ("生鲜食品", "冷藏食品")) else "normal"
    loc = query_one("""
        SELECT l.* FROM wms_location l JOIN wms_area a ON l.area_id=a.id
        WHERE a.warehouse_id=%s AND l.status='empty' AND l.type=%s AND a.type='storage'
        ORDER BY l.id LIMIT 1""", (warehouse_id, want_type), conn)
    if loc:
        return loc["id"]
    loc = query_one("""
        SELECT l.* FROM wms_location l JOIN wms_area a ON l.area_id=a.id
        WHERE a.warehouse_id=%s AND l.status='empty'
        ORDER BY l.id LIMIT 1""", (warehouse_id,), conn)
    if loc:
        return loc["id"]
    raise BizError(f"仓库内无可用空闲库位，无法为商品 {product['sku']} 上架")


def upsert_inventory(conn, warehouse_id, location_id, product_id, batch_no, qty):
    inv = query_one("""SELECT * FROM wms_inventory WHERE warehouse_id=%s AND location_id=%s
                       AND product_id=%s AND batch_no=%s""",
                    (warehouse_id, location_id, product_id, batch_no or ""), conn)
    if inv:
        execute("UPDATE wms_inventory SET quantity=quantity+%s, available_qty=available_qty+%s WHERE id=%s",
                (qty, qty, inv["id"]), conn)
        return inv["id"]
    return execute_return_id(
        """INSERT INTO wms_inventory (warehouse_id, location_id, product_id, batch_no, quantity, locked_qty, available_qty)
           VALUES (%s,%s,%s,%s,%s,0,%s)""",
        (warehouse_id, location_id, product_id, batch_no or "", qty, qty), conn)


def add_stock_move(conn, move_type, warehouse_id, from_loc, to_loc, product_id, batch_no, qty, ref_type, ref_no, operator):
    execute_return_id(
        """INSERT INTO wms_stock_move (move_type, warehouse_id, from_location_id, to_location_id, product_id,
           batch_no, quantity, ref_type, ref_no, operator) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (move_type, warehouse_id, from_loc, to_loc, product_id, batch_no or "", qty, ref_type, ref_no, operator), conn)


# ---------- 入库确认（联动：库存/批次/库位/移库记录/质检） ----------
def confirm_inbound(conn, inbound_id, user, inspections=None):
    """inspections: {detail_id: {"qualified_qty": int, "unqualified_qty": int}}"""
    order = query_one("SELECT * FROM wms_inbound_order WHERE id=%s", (inbound_id,), conn)
    if not order:
        raise BizError("入库单不存在")
    if order["status"] not in ("pending", "approved"):
        raise BizError(f"入库单状态为 {order['status']}，不可执行入库")
    details = query("SELECT * FROM wms_inbound_detail WHERE inbound_id=%s", (inbound_id,), conn)
    if not details:
        raise BizError("入库单没有明细")
    operator = user.get("username", "system")
    now = datetime.now()

    for d in details:
        product = query_one("SELECT * FROM wms_product WHERE id=%s", (d["product_id"],), conn)
        if not product:
            raise BizError(f"商品 id={d['product_id']} 不存在")
        insp = (inspections or {}).get(str(d["id"]), {}) or {}
        qualified = int(insp.get("qualified_qty", d["quantity"]))
        unqualified = int(insp.get("unqualified_qty", 0))
        if qualified + unqualified > d["quantity"]:
            raise BizError("质检合格数+不合格数不能超过收货数量")
        put_qty = qualified  # 合格品上架

        location_id = d.get("location_id")
        if not location_id:
            location_id = recommend_location(conn, order["warehouse_id"], product)

        if put_qty > 0:
            upsert_inventory(conn, order["warehouse_id"], location_id, d["product_id"], d.get("batch_no") or "", put_qty)
            # 库位占用
            execute("UPDATE wms_location SET status='occupied' WHERE id=%s AND status IN ('empty','locked')", (location_id,), conn)
            # 批次登记（明细指定了批次号即登记）
            if d.get("batch_no"):
                if not query_one("SELECT id FROM wms_batch WHERE product_id=%s AND batch_no=%s", (d["product_id"], d["batch_no"]), conn):
                    execute_return_id(
                        """INSERT INTO wms_batch (product_id, batch_no, production_date, expiry_date, supplier_id)
                           VALUES (%s,%s,%s,%s,%s)""",
                        (d["product_id"], d["batch_no"], d.get("production_date"), d.get("expiry_date"), order.get("supplier_id")), conn)
            # 移库记录
            add_stock_move(conn, "inbound", order["warehouse_id"], None, location_id, d["product_id"],
                           d.get("batch_no") or "", put_qty, "inbound", order["order_no"], operator)

        # 更新明细
        execute("UPDATE wms_inbound_detail SET received_qty=%s, location_id=%s WHERE id=%s",
                (qualified + unqualified, location_id, d["id"]), conn)
        # 质检记录
        result = "pass" if unqualified == 0 else ("unqualified" if qualified == 0 else "partial")
        execute_return_id(
            """INSERT INTO wms_inspection (inspection_no, inbound_id, product_id, quantity, qualified_qty,
               unqualified_qty, result, inspector, remark) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (gen_no(conn, "QC", "wms_inspection", "inspection_no"), inbound_id, d["product_id"], d["quantity"],
             qualified, unqualified, result, operator, "不合格品已退回供应商" if unqualified else ""), conn)

    execute("UPDATE wms_inbound_order SET status='completed', actual_time=%s WHERE id=%s", (now, inbound_id), conn)
    add_log(conn, user, "入库管理", "确认入库", f"入库单 {order['order_no']} 已完成入库")
    return {"order_no": order["order_no"]}


# ---------- 出库分配（FIFO 按批次先进先出，锁定库存） ----------
def allocate_outbound(conn, outbound_id, user):
    order = query_one("SELECT * FROM wms_outbound_order WHERE id=%s", (outbound_id,), conn)
    if not order:
        raise BizError("出库单不存在")
    if order["status"] != "approved":
        raise BizError(f"出库单状态为 {order['status']}，需先审核")
    details = query("SELECT * FROM wms_outbound_detail WHERE outbound_id=%s", (outbound_id,), conn)
    if not details:
        raise BizError("出库单没有明细")
    operator = user.get("username", "system")

    allocations = []
    for d in details:
        need = d["quantity"]
        # FIFO: 生产日期/到期日早的优先
        invs = query("""SELECT i.*, l.location_code FROM wms_inventory i
                        JOIN wms_location l ON i.location_id=l.id
                        WHERE i.warehouse_id=%s AND i.product_id=%s AND i.available_qty>0 AND i.status='normal'
                        ORDER BY i.batch_no='' , i.batch_no, i.update_time""",
                     (order["warehouse_id"], d["product_id"]), conn)
        stock = sum(i["available_qty"] for i in invs)
        if stock < need:
            product = query_one("SELECT sku FROM wms_product WHERE id=%s", (d["product_id"],), conn)
            raise BizError(f"商品 {product['sku']} 可用库存不足（需要 {need}，可用 {stock}）")
        for inv in invs:
            if need <= 0:
                break
            take = min(need, inv["available_qty"])
            execute("UPDATE wms_inventory SET locked_qty=locked_qty+%s, available_qty=available_qty-%s WHERE id=%s",
                    (take, take, inv["id"]), conn)
            execute("UPDATE wms_location SET status='locked' WHERE id=%s AND status='occupied'", (inv["location_id"],), conn)
            alloc_id = execute_return_id(
                """INSERT INTO wms_allocation (outbound_id, outbound_detail_id, inventory_id, product_id,
                   location_id, batch_no, quantity) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (outbound_id, d["id"], inv["id"], d["product_id"], inv["location_id"], inv["batch_no"], take), conn)
            allocations.append({"id": alloc_id, "batch_no": inv["batch_no"], "location_id": inv["location_id"], "qty": take})
            need -= take

    execute("UPDATE wms_outbound_order SET status='allocated' WHERE id=%s", (outbound_id,), conn)
    add_log(conn, user, "出库管理", "分配库存", f"出库单 {order['order_no']} 已按FIFO分配并锁定库存")
    return {"order_no": order["order_no"], "allocations": allocations}


# ---------- 出库发货（扣减库存、释放库位、移库记录） ----------
def ship_outbound(conn, outbound_id, user):
    order = query_one("SELECT * FROM wms_outbound_order WHERE id=%s", (outbound_id,), conn)
    if not order:
        raise BizError("出库单不存在")
    if order["status"] not in ("allocated", "picked"):
        raise BizError("出库单需先分配库存")
    operator = user.get("username", "system")
    allocations = query("SELECT * FROM wms_allocation WHERE outbound_id=%s", (outbound_id,), conn)
    if not allocations:
        raise BizError("无库存分配记录")

    for a in allocations:
        inv = query_one("SELECT * FROM wms_inventory WHERE id=%s", (a["inventory_id"],), conn)
        if not inv or inv["quantity"] < a["quantity"]:
            raise BizError("库存数据异常，请刷新后重试")
        execute("""UPDATE wms_inventory SET quantity=quantity-%s, locked_qty=locked_qty-%s
                   WHERE id=%s""", (a["quantity"], a["quantity"], inv["id"]), conn)
        # 库存清零则删除记录并释放库位
        inv2 = query_one("SELECT quantity FROM wms_inventory WHERE id=%s", (inv["id"],), conn)
        if inv2["quantity"] <= 0:
            execute("DELETE FROM wms_inventory WHERE id=%s", (inv["id"],), conn)
            remain = query_one("SELECT COUNT(*) c FROM wms_inventory WHERE location_id=%s AND quantity>0",
                               (inv["location_id"],), conn)["c"]
            if remain == 0:
                execute("UPDATE wms_location SET status='empty' WHERE id=%s", (inv["location_id"],), conn)
            else:
                execute("UPDATE wms_location SET status='occupied' WHERE id=%s AND status='locked'", (inv["location_id"],), conn)
        else:
            # 该库位仍有库存，发货后恢复为占用状态
            execute("UPDATE wms_location SET status='occupied' WHERE id=%s AND status='locked'", (inv["location_id"],), conn)
        # 移库记录
        add_stock_move(conn, "outbound", order["warehouse_id"], a["location_id"], None, a["product_id"],
                       a["batch_no"], a["quantity"], "outbound", order["order_no"], operator)
        # 更新明细拣货数
        execute("UPDATE wms_outbound_detail SET picked_qty=picked_qty+%s, batch_no=%s, location_id=%s WHERE id=%s",
                (a["quantity"], a["batch_no"], a["location_id"], a["outbound_detail_id"]), conn)

    execute("DELETE FROM wms_allocation WHERE outbound_id=%s", (outbound_id,), conn)
    execute("UPDATE wms_outbound_order SET status='shipped', actual_time=%s WHERE id=%s", (datetime.now(), outbound_id), conn)
    add_log(conn, user, "出库管理", "发货确认", f"出库单 {order['order_no']} 已发货，库存已扣减")
    return {"order_no": order["order_no"]}


def release_outbound(conn, outbound_id, user):
    """取消出库单时释放锁定的库存"""
    allocations = query("SELECT * FROM wms_allocation WHERE outbound_id=%s", (outbound_id,), conn)
    for a in allocations:
        execute("UPDATE wms_inventory SET locked_qty=GREATEST(locked_qty-%s,0), available_qty=available_qty+%s WHERE id=%s",
                (a["quantity"], a["quantity"], a["inventory_id"]), conn)
        execute("UPDATE wms_location SET status='occupied' WHERE id=%s AND status='locked'", (a["location_id"],), conn)
    if allocations:
        execute("DELETE FROM wms_allocation WHERE outbound_id=%s", (outbound_id,), conn)


# ---------- 盘点提交（差异生成调整单并联动库存） ----------
def submit_check(conn, check_id, user, actuals):
    """actuals: {detail_id: actual_qty}"""
    order = query_one("SELECT * FROM wms_check_order WHERE id=%s", (check_id,), conn)
    if not order:
        raise BizError("盘点单不存在")
    if order["status"] == "completed":
        raise BizError("盘点单已完成")
    details = query("SELECT * FROM wms_check_detail WHERE check_id=%s", (check_id,), conn)
    operator = user.get("username", "system")
    diff_count = 0

    for d in details:
        actual = actuals.get(str(d["id"]))
        if actual is None:
            actual = d["book_qty"]
        actual = int(actual)
        diff = actual - d["book_qty"]
        execute("UPDATE wms_check_detail SET actual_qty=%s, diff_qty=%s WHERE id=%s", (actual, diff, d["id"]), conn)
        if diff != 0:
            diff_count += 1
            inv = query_one("""SELECT * FROM wms_inventory WHERE warehouse_id=%s AND location_id=%s
                               AND product_id=%s AND batch_no=%s""",
                            (order["warehouse_id"], d["location_id"], d["product_id"], d["batch_no"]), conn)
            before = inv["quantity"] if inv else 0
            if actual > 0 and inv:
                execute("UPDATE wms_inventory SET quantity=%s, available_qty=%s WHERE id=%s", (actual, actual - inv["locked_qty"], inv["id"]), conn)
            elif actual <= 0 and inv:
                execute("DELETE FROM wms_inventory WHERE id=%s", (inv["id"],), conn)
                execute("UPDATE wms_location SET status='empty' WHERE id=%s", (d["location_id"],), conn)
            reason = "surplus" if diff > 0 else "loss"
            execute_return_id(
                """INSERT INTO wms_adjustment (adjust_no, warehouse_id, product_id, batch_no, location_id,
                   before_qty, after_qty, diff_qty, reason, operator) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (gen_no(conn, "ADJ", "wms_adjustment", "adjust_no"), order["warehouse_id"], d["product_id"],
                 d["batch_no"], d["location_id"], before, actual, diff, reason, operator), conn)
            add_stock_move(conn, "check", order["warehouse_id"], d["location_id"], None, d["product_id"],
                           d["batch_no"], abs(diff), "check", order["check_no"], operator)

    execute("""UPDATE wms_check_order SET status='completed', end_time=%s WHERE id=%s""",
            (datetime.now(), check_id), conn)
    add_log(conn, user, "盘点管理", "提交盘点", f"盘点单 {order['check_no']} 完成，差异 {diff_count} 条已生成调整单")
    return {"check_no": order["check_no"], "diff_count": diff_count}
