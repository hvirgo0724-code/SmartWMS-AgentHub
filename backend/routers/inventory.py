"""库存管理：实时库存/移动/调整/冻结/盘点/批次效期"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from database import query, query_one, execute, execute_return_id, transaction, add_log
from deps import get_current_user, require_perm, ok, fail
from services import gen_no, submit_check, add_stock_move, BizError
from datetime import datetime, date, timedelta

router = APIRouter(tags=["库存管理"])


# ---------- 实时库存查询 ----------
@router.get("/inventory")
def list_inventory(warehouse_id: Optional[int] = None, location_id: Optional[int] = None,
                   product_id: Optional[int] = None, batch_no: str = "", keyword: str = "",
                   status: str = "", page: int = 1, size: int = 15, user: dict = Depends(get_current_user)):
    where, params = "1=1", []
    if warehouse_id:
        where += " AND i.warehouse_id=%s"
        params.append(warehouse_id)
    if location_id:
        where += " AND i.location_id=%s"
        params.append(location_id)
    if product_id:
        where += " AND i.product_id=%s"
        params.append(product_id)
    if batch_no:
        where += " AND i.batch_no=%s"
        params.append(batch_no)
    if status:
        where += " AND i.status=%s"
        params.append(status)
    if keyword:
        where += " AND (p.product_name LIKE %s OR p.sku LIKE %s OR l.location_code LIKE %s)"
        params += [f"%{keyword}%"] * 3
    total = query_one(f"""SELECT COUNT(*) c FROM wms_inventory i
                          JOIN wms_product p ON i.product_id=p.id
                          JOIN wms_location l ON i.location_id=l.id WHERE {where}""", params)["c"]
    sum_row = query_one(f"""SELECT COALESCE(SUM(i.quantity),0) qty, COALESCE(SUM(i.available_qty),0) avail,
                            COALESCE(SUM(i.locked_qty),0) locked FROM wms_inventory i
                            JOIN wms_product p ON i.product_id=p.id
                            JOIN wms_location l ON i.location_id=l.id WHERE {where}""", params)
    rows = query(f"""SELECT i.*, p.sku, p.product_name, p.unit, p.category, p.price, l.location_code,
                            w.warehouse_name
                     FROM wms_inventory i
                     JOIN wms_product p ON i.product_id=p.id
                     JOIN wms_location l ON i.location_id=l.id
                     JOIN wms_warehouse w ON i.warehouse_id=w.id
                     WHERE {where} ORDER BY i.update_time DESC LIMIT %s OFFSET %s""",
                 params + [size, (page - 1) * size])
    for r in rows:
        r["stock_value"] = round((r["quantity"] or 0) * float(r["price"] or 0), 2)
    return ok({"total": total, "list": rows, "summary": sum_row})


@router.get("/inventory/moves")
def list_moves(move_type: str = "", page: int = 1, size: int = 15, user: dict = Depends(get_current_user)):
    where, params = "1=1", []
    if move_type:
        where += " AND m.move_type=%s"
        params.append(move_type)
    total = query_one(f"SELECT COUNT(*) c FROM wms_stock_move m WHERE {where}", params)["c"]
    rows = query(f"""SELECT m.*, p.sku, p.product_name, fl.location_code from_loc, tl.location_code to_loc
                     FROM wms_stock_move m
                     JOIN wms_product p ON m.product_id=p.id
                     LEFT JOIN wms_location fl ON m.from_location_id=fl.id
                     LEFT JOIN wms_location tl ON m.to_location_id=tl.id
                     WHERE {where} ORDER BY m.id DESC LIMIT %s OFFSET %s""",
                 params + [size, (page - 1) * size])
    return ok({"total": total, "list": rows})


# ---------- 库存移动 ----------
class MoveBody(BaseModel):
    inventory_id: int
    to_location_id: int
    quantity: int


@router.post("/inventory/move")
def move_inventory(body: MoveBody, user: dict = Depends(require_perm("inventory:move"))):
    inv = query_one("SELECT * FROM wms_inventory WHERE id=%s", (body.inventory_id,))
    if not inv:
        return fail("库存记录不存在")
    if inv["status"] == "frozen":
        return fail("库存已冻结，不可移动")
    if body.quantity <= 0 or body.quantity > inv["quantity"]:
        return fail(f"移动数量需在 1~{inv['quantity']} 之间")
    if body.to_location_id == inv["location_id"]:
        return fail("目标库位与原库位相同")
    target = query_one("SELECT * FROM wms_location WHERE id=%s", (body.to_location_id,))
    if not target:
        return fail("目标库位不存在")
    if target["status"] == "locked":
        return fail("目标库位已锁定")
    try:
        with transaction() as conn:
            # 原库位扣减
            remain = inv["quantity"] - body.quantity
            if remain > 0:
                execute("UPDATE wms_inventory SET quantity=quantity-%s, available_qty=available_qty-%s WHERE id=%s",
                        (body.quantity, body.quantity, inv["id"]), conn)
            else:
                if inv["locked_qty"] > 0:
                    raise BizError("该记录存在锁定库存，不可全部移出")
                execute("DELETE FROM wms_inventory WHERE id=%s", (inv["id"],), conn)
            # 目标库位增加
            from services import upsert_inventory
            upsert_inventory(conn, inv["warehouse_id"], target["id"], inv["product_id"], inv["batch_no"], body.quantity)
            execute("UPDATE wms_location SET status='occupied' WHERE id=%s AND status='empty'", (target["id"],), conn)
            # 原库位可能清空
            remain_cnt = query_one("SELECT COUNT(*) c FROM wms_inventory WHERE location_id=%s AND quantity>0",
                                   (inv["location_id"],), conn)["c"]
            if remain_cnt == 0:
                execute("UPDATE wms_location SET status='empty' WHERE id=%s", (inv["location_id"],), conn)
            add_stock_move(conn, "move", inv["warehouse_id"], inv["location_id"], target["id"],
                           inv["product_id"], inv["batch_no"], body.quantity, "move", "", user["username"])
            add_log(conn, user, "库存管理", "库存移动", f"商品id={inv['product_id']} {body.quantity}件 库位{inv['location_id']}→{target['id']}")
        return ok(msg="移动成功")
    except BizError as e:
        return fail(e.msg)


# ---------- 库存调整 ----------
class AdjustBody(BaseModel):
    inventory_id: int
    adjust_qty: int  # 正数盘盈 负数盘亏
    reason: str = "manual"


@router.post("/inventory/adjust")
def adjust_inventory(body: AdjustBody, user: dict = Depends(require_perm("inventory:adjust"))):
    inv = query_one("SELECT * FROM wms_inventory WHERE id=%s", (body.inventory_id,))
    if not inv:
        return fail("库存记录不存在")
    after = inv["quantity"] + body.adjust_qty
    if after < 0:
        return fail(f"调整后数量为负（当前 {inv['quantity']}）")
    if after < inv["locked_qty"]:
        return fail(f"调整后数量低于锁定数量 {inv['locked_qty']}")
    try:
        with transaction() as conn:
            if after == 0:
                execute("DELETE FROM wms_inventory WHERE id=%s", (inv["id"],), conn)
                execute("UPDATE wms_location SET status='empty' WHERE id=%s", (inv["location_id"],), conn)
            else:
                execute("UPDATE wms_inventory SET quantity=%s, available_qty=%s WHERE id=%s",
                        (after, after - inv["locked_qty"], inv["id"]), conn)
            execute_return_id(
                """INSERT INTO wms_adjustment (adjust_no, warehouse_id, product_id, batch_no, location_id,
                   before_qty, after_qty, diff_qty, reason, operator) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (gen_no(conn, "ADJ", "wms_adjustment", "adjust_no"), inv["warehouse_id"], inv["product_id"],
                 inv["batch_no"], inv["location_id"], inv["quantity"], after, body.adjust_qty, body.reason, user["username"]), conn)
            add_stock_move(conn, "adjust", inv["warehouse_id"], inv["location_id"], None, inv["product_id"],
                           inv["batch_no"], abs(body.adjust_qty), "adjust", "", user["username"])
            add_log(conn, user, "库存管理", "库存调整", f"库存id={inv['id']} 调整 {body.adjust_qty:+d}（{body.reason}）")
        return ok(msg="调整成功")
    except BizError as e:
        return fail(e.msg)


@router.get("/adjustments")
def list_adjustments(user: dict = Depends(get_current_user)):
    rows = query("""SELECT a.*, p.sku, p.product_name, l.location_code, w.warehouse_name FROM wms_adjustment a
                    JOIN wms_product p ON a.product_id=p.id
                    LEFT JOIN wms_location l ON a.location_id=l.id
                    JOIN wms_warehouse w ON a.warehouse_id=w.id ORDER BY a.id DESC LIMIT 200""")
    return ok(rows)


# ---------- 库存冻结/解冻 ----------
class FreezeBody(BaseModel):
    inventory_ids: list[int]
    action: str = "freeze"  # freeze / unfreeze


@router.post("/inventory/freeze")
def freeze_inventory(body: FreezeBody, user: dict = Depends(require_perm("inventory:adjust"))):
    status = "frozen" if body.action == "freeze" else "normal"
    ids = ",".join(map(str, body.inventory_ids))
    execute(f"UPDATE wms_inventory SET status=%s WHERE id IN ({ids})", (status,))
    add_log(None, user, "库存管理", "库存冻结" if status == "frozen" else "库存解冻",
            f"库存记录 {ids} 状态改为 {status}")
    return ok(msg="冻结成功" if status == "frozen" else "解冻成功")


# ---------- 盘点管理 ----------
class CheckBody(BaseModel):
    warehouse_id: int
    area_id: Optional[int] = None
    type: str = "cycle"
    blind: int = 0


@router.get("/check-orders")
def list_checks(status: str = "", user: dict = Depends(get_current_user)):
    where, params = "1=1", []
    if status:
        where += " AND c.status=%s"
        params.append(status)
    rows = query(f"""SELECT c.*, w.warehouse_name, a.area_name FROM wms_check_order c
                     JOIN wms_warehouse w ON c.warehouse_id=w.id
                     LEFT JOIN wms_area a ON c.area_id=a.id WHERE {where} ORDER BY c.id DESC""", params)
    for c in rows:
        c["detail_count"] = query_one("SELECT COUNT(*) c FROM wms_check_detail WHERE check_id=%s", (c["id"],))["c"]
        c["diff_count"] = query_one("SELECT COUNT(*) c FROM wms_check_detail WHERE check_id=%s AND diff_qty<>0", (c["id"],))["c"]
    return ok(rows)


@router.get("/check-orders/{cid}")
def get_check(cid: int, user: dict = Depends(get_current_user)):
    order = query_one("""SELECT c.*, w.warehouse_name, a.area_name FROM wms_check_order c
                         JOIN wms_warehouse w ON c.warehouse_id=w.id
                         LEFT JOIN wms_area a ON c.area_id=a.id WHERE c.id=%s""", (cid,))
    if not order:
        return fail("盘点单不存在")
    order["details"] = query("""SELECT d.*, p.sku, p.product_name, p.unit, l.location_code FROM wms_check_detail d
                                JOIN wms_product p ON d.product_id=p.id
                                LEFT JOIN wms_location l ON d.location_id=l.id
                                WHERE d.check_id=%s""", (cid,))
    return ok(order)


@router.post("/check-orders")
def create_check(body: CheckBody, user: dict = Depends(require_perm("check:add"))):
    where, params = "i.warehouse_id=%s", [body.warehouse_id]
    if body.area_id:
        where += " AND l.area_id=%s"
        params.append(body.area_id)
    invs = query(f"""SELECT i.*, l.location_code FROM wms_inventory i
                     JOIN wms_location l ON i.location_id=l.id
                     WHERE {where} AND i.quantity>0 ORDER BY l.location_code""", params)
    if not invs:
        return fail("范围内没有在库库存")
    try:
        with transaction() as conn:
            check_no = gen_no(conn, "CK", "wms_check_order", "check_no")
            cid = execute_return_id(
                """INSERT INTO wms_check_order (check_no, warehouse_id, area_id, type, blind, status, operator, start_time)
                   VALUES (%s,%s,%s,%s,%s,'checking',%s,%s)""",
                (check_no, body.warehouse_id, body.area_id, body.type, body.blind, user["username"], datetime.now()), conn)
            for i in invs:
                execute("""INSERT INTO wms_check_detail (check_id, location_id, product_id, batch_no, book_qty)
                           VALUES (%s,%s,%s,%s,%s)""",
                        (cid, i["location_id"], i["product_id"], i["batch_no"], i["quantity"]), conn)
            add_log(conn, user, "盘点管理", "创建盘点单", f"创建盘点单 {check_no}，共 {len(invs)} 条库存")
        return ok({"id": cid, "check_no": check_no, "count": len(invs)}, f"盘点单已生成，共 {len(invs)} 条库存记录")
    except BizError as e:
        return fail(e.msg)


@router.post("/check-orders/{cid}/submit")
def submit_check_api(cid: int, body: dict, user: dict = Depends(require_perm("check:add"))):
    """提交盘点结果: {actuals: {detail_id: actual_qty}}"""
    try:
        with transaction() as conn:
            result = submit_check(conn, cid, user, (body or {}).get("actuals") or {})
        return ok(result, "盘点完成，差异已生成调整单并同步库存")
    except BizError as e:
        return fail(e.msg)


# ---------- 批次与效期 ----------
@router.get("/batches")
def list_batches(expiring_days: int = 0, user: dict = Depends(get_current_user)):
    where, params = "1=1", []
    if expiring_days > 0:
        where += " AND b.expiry_date IS NOT NULL AND b.expiry_date <= DATE_ADD(CURDATE(), INTERVAL %s DAY)"
        params.append(expiring_days)
    rows = query(f"""SELECT b.*, p.sku, p.product_name, p.unit, p.shelf_life,
                            COALESCE((SELECT SUM(i.quantity) FROM wms_inventory i
                                      WHERE i.product_id=b.product_id AND i.batch_no=b.batch_no),0) stock_qty
                     FROM wms_batch b JOIN wms_product p ON b.product_id=p.id
                     WHERE {where} ORDER BY b.expiry_date IS NULL, b.expiry_date LIMIT 200""", params)
    for r in rows:
        if r["expiry_date"]:
            r["days_left"] = (r["expiry_date"] - date.today()).days
        else:
            r["days_left"] = None
    return ok(rows)
