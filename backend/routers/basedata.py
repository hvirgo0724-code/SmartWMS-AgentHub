"""基础数据：仓库/库区/库位/商品/供应商/客户"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional
from database import query, query_one, execute, execute_return_id, add_log
from deps import get_current_user, require_perm, ok, fail

router = APIRouter(tags=["基础管理"])


# ---------- 仓库 ----------
class WarehouseBody(BaseModel):
    warehouse_code: str
    warehouse_name: str
    address: str = ""
    type: str = "normal"
    area: float = 0
    status: int = 1


@router.get("/warehouses")
def list_warehouses(keyword: str = "", user: dict = Depends(get_current_user)):
    where, params = "1=1", []
    if keyword:
        where += " AND (warehouse_name LIKE %s OR warehouse_code LIKE %s)"
        params += [f"%{keyword}%"] * 2
    rows = query(f"SELECT * FROM wms_warehouse WHERE {where} ORDER BY id", params)
    for w in rows:
        w["area_count"] = query_one("SELECT COUNT(*) c FROM wms_area WHERE warehouse_id=%s", (w["id"],))["c"]
        w["location_count"] = query_one(
            "SELECT COUNT(*) c FROM wms_location l JOIN wms_area a ON l.area_id=a.id WHERE a.warehouse_id=%s", (w["id"],))["c"]
    return ok(rows)


@router.post("/warehouses")
def create_warehouse(body: WarehouseBody, user: dict = Depends(require_perm("warehouse:add"))):
    if query_one("SELECT id FROM wms_warehouse WHERE warehouse_code=%s", (body.warehouse_code,)):
        return fail("仓库编码已存在")
    wid = execute_return_id("""INSERT INTO wms_warehouse (warehouse_code, warehouse_name, address, type, area, status)
                     VALUES (%s,%s,%s,%s,%s,%s)""",
                  (body.warehouse_code, body.warehouse_name, body.address, body.type, body.area, body.status))
    add_log(None, user, "仓库管理", "新增", f"创建仓库 {body.warehouse_code}")
    return ok({"id": wid}, "创建成功")


@router.put("/warehouses/{wid}")
def update_warehouse(wid: int, body: WarehouseBody, user: dict = Depends(require_perm("warehouse:edit"))):
    execute("""UPDATE wms_warehouse SET warehouse_code=%s, warehouse_name=%s, address=%s, type=%s, area=%s, status=%s
               WHERE id=%s""",
            (body.warehouse_code, body.warehouse_name, body.address, body.type, body.area, body.status, wid))
    add_log(None, user, "仓库管理", "修改", f"更新仓库 id={wid}")
    return ok(msg="更新成功")


@router.delete("/warehouses/{wid}")
def delete_warehouse(wid: int, user: dict = Depends(require_perm("warehouse:delete"))):
    if query_one("SELECT 1 FROM wms_area WHERE warehouse_id=%s LIMIT 1", (wid,)):
        return fail("该仓库下存在库区，无法删除")
    execute("DELETE FROM wms_warehouse WHERE id=%s", (wid,))
    add_log(None, user, "仓库管理", "删除", f"删除仓库 id={wid}")
    return ok(msg="删除成功")


# ---------- 库区 ----------
class AreaBody(BaseModel):
    warehouse_id: int
    area_code: str
    area_name: str
    type: str = "storage"
    capacity: int = 0


@router.get("/areas")
def list_areas(warehouse_id: Optional[int] = None, user: dict = Depends(get_current_user)):
    where, params = "1=1", []
    if warehouse_id:
        where += " AND a.warehouse_id=%s"
        params.append(warehouse_id)
    rows = query(f"""SELECT a.*, w.warehouse_name FROM wms_area a
                     JOIN wms_warehouse w ON a.warehouse_id=w.id WHERE {where} ORDER BY a.id""", params)
    for a in rows:
        a["location_count"] = query_one("SELECT COUNT(*) c FROM wms_location WHERE area_id=%s", (a["id"],))["c"]
    return ok(rows)


@router.post("/areas")
def create_area(body: AreaBody, user: dict = Depends(require_perm("area:add"))):
    if query_one("SELECT id FROM wms_area WHERE area_code=%s", (body.area_code,)):
        return fail("库区编码已存在")
    aid = execute_return_id("INSERT INTO wms_area (warehouse_id, area_code, area_name, type, capacity) VALUES (%s,%s,%s,%s,%s)",
                  (body.warehouse_id, body.area_code, body.area_name, body.type, body.capacity))
    add_log(None, user, "库区管理", "新增", f"创建库区 {body.area_code}")
    return ok({"id": aid}, "创建成功")


@router.put("/areas/{aid}")
def update_area(aid: int, body: AreaBody, user: dict = Depends(require_perm("area:edit"))):
    execute("UPDATE wms_area SET warehouse_id=%s, area_code=%s, area_name=%s, type=%s, capacity=%s WHERE id=%s",
            (body.warehouse_id, body.area_code, body.area_name, body.type, body.capacity, aid))
    add_log(None, user, "库区管理", "修改", f"更新库区 id={aid}")
    return ok(msg="更新成功")


@router.delete("/areas/{aid}")
def delete_area(aid: int, user: dict = Depends(require_perm("area:delete"))):
    if query_one("SELECT 1 FROM wms_location WHERE area_id=%s LIMIT 1", (aid,)):
        return fail("该库区下存在库位，无法删除")
    execute("DELETE FROM wms_area WHERE id=%s", (aid,))
    add_log(None, user, "库区管理", "删除", f"删除库区 id={aid}")
    return ok(msg="删除成功")


# ---------- 库位 ----------
class LocationBody(BaseModel):
    area_id: int
    location_code: str
    type: str = "normal"
    max_weight: float = 500
    max_volume: float = 10
    status: str = "empty"


@router.get("/locations")
def list_locations(area_id: Optional[int] = None, warehouse_id: Optional[int] = None,
                   status: str = "", keyword: str = "", page: int = 1, size: int = 20,
                   user: dict = Depends(get_current_user)):
    where, params = "1=1", []
    if area_id:
        where += " AND l.area_id=%s"
        params.append(area_id)
    if warehouse_id:
        where += " AND a.warehouse_id=%s"
        params.append(warehouse_id)
    if status:
        where += " AND l.status=%s"
        params.append(status)
    if keyword:
        where += " AND l.location_code LIKE %s"
        params.append(f"%{keyword}%")
    total = query_one(f"""SELECT COUNT(*) c FROM wms_location l JOIN wms_area a ON l.area_id=a.id WHERE {where}""", params)["c"]
    rows = query(f"""SELECT l.*, a.area_name, a.warehouse_id, w.warehouse_name FROM wms_location l
                     JOIN wms_area a ON l.area_id=a.id JOIN wms_warehouse w ON a.warehouse_id=w.id
                     WHERE {where} ORDER BY l.id LIMIT %s OFFSET %s""", params + [size, (page - 1) * size])
    return ok({"total": total, "list": rows})


@router.post("/locations")
def create_location(body: LocationBody, user: dict = Depends(require_perm("location:add"))):
    if query_one("SELECT id FROM wms_location WHERE location_code=%s", (body.location_code,)):
        return fail("库位编码已存在")
    lid = execute_return_id("""INSERT INTO wms_location (area_id, location_code, type, max_weight, max_volume, status)
                     VALUES (%s,%s,%s,%s,%s,%s)""",
                  (body.area_id, body.location_code, body.type, body.max_weight, body.max_volume, body.status))
    add_log(None, user, "库位管理", "新增", f"创建库位 {body.location_code}")
    return ok({"id": lid}, "创建成功")


@router.post("/locations/batch")
def batch_create_locations(body: dict, user: dict = Depends(require_perm("location:add"))):
    """批量生成库位: {area_id, prefix, rows, cols, type}"""
    area_id, prefix = body["area_id"], body.get("prefix", "L")
    rows, cols = int(body.get("rows", 3)), int(body.get("cols", 10))
    loc_type = body.get("type", "normal")
    area = query_one("SELECT * FROM wms_area WHERE id=%s", (area_id,))
    if not area:
        return fail("库区不存在")
    created = 0
    for r in range(1, rows + 1):
        for c in range(1, cols + 1):
            code = f"{prefix}-{r:02d}{c:02d}"
            if not query_one("SELECT id FROM wms_location WHERE location_code=%s", (code,)):
                execute("INSERT INTO wms_location (area_id, location_code, type, status) VALUES (%s,%s,%s,'empty')",
                        (area_id, code, loc_type))
                created += 1
    add_log(None, user, "库位管理", "批量新增", f"库区 {area['area_code']} 批量生成 {created} 个库位")
    return ok({"created": created}, f"成功生成 {created} 个库位")


@router.put("/locations/{lid}")
def update_location(lid: int, body: LocationBody, user: dict = Depends(require_perm("location:edit"))):
    execute("""UPDATE wms_location SET area_id=%s, location_code=%s, type=%s, max_weight=%s, max_volume=%s, status=%s
               WHERE id=%s""",
            (body.area_id, body.location_code, body.type, body.max_weight, body.max_volume, body.status, lid))
    add_log(None, user, "库位管理", "修改", f"更新库位 id={lid}")
    return ok(msg="更新成功")


@router.delete("/locations/{lid}")
def delete_location(lid: int, user: dict = Depends(require_perm("location:delete"))):
    if query_one("SELECT 1 FROM wms_inventory WHERE location_id=%s AND quantity>0 LIMIT 1", (lid,)):
        return fail("该库位仍有库存，无法删除")
    execute("DELETE FROM wms_location WHERE id=%s", (lid,))
    add_log(None, user, "库位管理", "删除", f"删除库位 id={lid}")
    return ok(msg="删除成功")


# ---------- 商品 ----------
class ProductBody(BaseModel):
    sku: str
    barcode: str = ""
    product_name: str
    category: str = ""
    unit: str = "件"
    weight: float = 0
    volume: float = 0
    shelf_life: int = 0
    is_batch_managed: int = 1
    min_stock: int = 0
    max_stock: int = 0
    price: float = 0
    supplier_id: Optional[int] = None
    status: int = 1


@router.get("/products")
def list_products(page: int = 1, size: int = 10, keyword: str = "", category: str = "",
                  user: dict = Depends(get_current_user)):
    where, params = "1=1", []
    if keyword:
        where += " AND (product_name LIKE %s OR sku LIKE %s OR barcode LIKE %s)"
        params += [f"%{keyword}%"] * 3
    if category:
        where += " AND category=%s"
        params.append(category)
    total = query_one(f"SELECT COUNT(*) c FROM wms_product WHERE {where}", params)["c"]
    # 一次聚合查询替代逐商品统计，避免分页 N+1
    rows = query(f"""SELECT p.*, MAX(s.supplier_name) supplier_name,
                            COALESCE(SUM(i.quantity),0) stock_qty,
                            COALESCE(SUM(i.available_qty),0) available_qty
                     FROM wms_product p
                     LEFT JOIN wms_supplier s ON p.supplier_id=s.id
                     LEFT JOIN wms_inventory i ON i.product_id=p.id
                     WHERE {where} GROUP BY p.id ORDER BY p.id LIMIT %s OFFSET %s""",
                 params + [size, (page - 1) * size])
    return ok({"total": total, "list": rows})


@router.post("/products")
def create_product(body: ProductBody, user: dict = Depends(require_perm("product:add"))):
    if query_one("SELECT id FROM wms_product WHERE sku=%s", (body.sku,)):
        return fail("SKU已存在")
    pid = execute_return_id("""INSERT INTO wms_product (sku, barcode, product_name, category, unit, weight, volume,
                     shelf_life, is_batch_managed, min_stock, max_stock, price, supplier_id, status)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                  (body.sku, body.barcode, body.product_name, body.category, body.unit, body.weight, body.volume,
                   body.shelf_life, body.is_batch_managed, body.min_stock, body.max_stock, body.price,
                   body.supplier_id, body.status))
    add_log(None, user, "商品管理", "新增", f"创建商品 {body.sku}")
    return ok({"id": pid}, "创建成功")


@router.put("/products/{pid}")
def update_product(pid: int, body: ProductBody, user: dict = Depends(require_perm("product:edit"))):
    execute("""UPDATE wms_product SET sku=%s, barcode=%s, product_name=%s, category=%s, unit=%s, weight=%s,
               volume=%s, shelf_life=%s, is_batch_managed=%s, min_stock=%s, max_stock=%s, price=%s,
               supplier_id=%s, status=%s WHERE id=%s""",
            (body.sku, body.barcode, body.product_name, body.category, body.unit, body.weight, body.volume,
             body.shelf_life, body.is_batch_managed, body.min_stock, body.max_stock, body.price,
             body.supplier_id, body.status, pid))
    add_log(None, user, "商品管理", "修改", f"更新商品 {body.sku}")
    return ok(msg="更新成功")


@router.delete("/products/{pid}")
def delete_product(pid: int, user: dict = Depends(require_perm("product:delete"))):
    if query_one("SELECT 1 FROM wms_inventory WHERE product_id=%s AND quantity>0 LIMIT 1", (pid,)):
        return fail("该商品仍有库存，无法删除")
    execute("DELETE FROM wms_product WHERE id=%s", (pid,))
    add_log(None, user, "商品管理", "删除", f"删除商品 id={pid}")
    return ok(msg="删除成功")


@router.get("/products/categories")
def list_categories(user: dict = Depends(get_current_user)):
    return ok([r["category"] for r in query("SELECT DISTINCT category FROM wms_product WHERE category IS NOT NULL AND category<>''")])


# ---------- 供应商 / 客户 ----------
class PartnerBody(BaseModel):
    code: str
    name: str
    contact: str = ""
    phone: str = ""
    address: str = ""
    status: int = 1


@router.get("/suppliers")
def list_suppliers(keyword: str = "", user: dict = Depends(get_current_user)):
    where, params = "1=1", []
    if keyword:
        where += " AND (supplier_name LIKE %s OR supplier_code LIKE %s)"
        params += [f"%{keyword}%"] * 2
    rows = query(f"""SELECT s.*, COUNT(o.id) inbound_count FROM wms_supplier s
                     LEFT JOIN wms_inbound_order o ON o.supplier_id=s.id
                     WHERE {where} GROUP BY s.id ORDER BY s.id""", params)
    return ok(rows)


@router.post("/suppliers")
def create_supplier(body: PartnerBody, user: dict = Depends(require_perm("supplier:add"))):
    if query_one("SELECT id FROM wms_supplier WHERE supplier_code=%s", (body.code,)):
        return fail("供应商编码已存在")
    sid = execute_return_id("INSERT INTO wms_supplier (supplier_code, supplier_name, contact, phone, address, status) VALUES (%s,%s,%s,%s,%s,%s)",
                  (body.code, body.name, body.contact, body.phone, body.address, body.status))
    add_log(None, user, "供应商管理", "新增", f"创建供应商 {body.name}")
    return ok({"id": sid}, "创建成功")


@router.put("/suppliers/{sid}")
def update_supplier(sid: int, body: PartnerBody, user: dict = Depends(require_perm("supplier:edit"))):
    execute("UPDATE wms_supplier SET supplier_code=%s, supplier_name=%s, contact=%s, phone=%s, address=%s, status=%s WHERE id=%s",
            (body.code, body.name, body.contact, body.phone, body.address, body.status, sid))
    add_log(None, user, "供应商管理", "修改", f"更新供应商 id={sid}")
    return ok(msg="更新成功")


@router.delete("/suppliers/{sid}")
def delete_supplier(sid: int, user: dict = Depends(require_perm("supplier:delete"))):
    if query_one("SELECT 1 FROM wms_inbound_order WHERE supplier_id=%s LIMIT 1", (sid,)):
        return fail("该供应商存在入库单记录，无法删除")
    execute("DELETE FROM wms_supplier WHERE id=%s", (sid,))
    add_log(None, user, "供应商管理", "删除", f"删除供应商 id={sid}")
    return ok(msg="删除成功")


@router.get("/customers")
def list_customers(keyword: str = "", user: dict = Depends(get_current_user)):
    where, params = "1=1", []
    if keyword:
        where += " AND (customer_name LIKE %s OR customer_code LIKE %s)"
        params += [f"%{keyword}%"] * 2
    rows = query(f"""SELECT c.*, COUNT(o.id) outbound_count FROM wms_customer c
                     LEFT JOIN wms_outbound_order o ON o.customer_id=c.id
                     WHERE {where} GROUP BY c.id ORDER BY c.id""", params)
    return ok(rows)


@router.post("/customers")
def create_customer(body: PartnerBody, user: dict = Depends(require_perm("customer:add"))):
    if query_one("SELECT id FROM wms_customer WHERE customer_code=%s", (body.code,)):
        return fail("客户编码已存在")
    cid = execute_return_id("INSERT INTO wms_customer (customer_code, customer_name, contact, phone, address, status) VALUES (%s,%s,%s,%s,%s,%s)",
                  (body.code, body.name, body.contact, body.phone, body.address, body.status))
    add_log(None, user, "客户管理", "新增", f"创建客户 {body.name}")
    return ok({"id": cid}, "创建成功")


@router.put("/customers/{cid}")
def update_customer(cid: int, body: PartnerBody, user: dict = Depends(require_perm("customer:edit"))):
    execute("UPDATE wms_customer SET customer_code=%s, customer_name=%s, contact=%s, phone=%s, address=%s, status=%s WHERE id=%s",
            (body.code, body.name, body.contact, body.phone, body.address, body.status, cid))
    add_log(None, user, "客户管理", "修改", f"更新客户 id={cid}")
    return ok(msg="更新成功")


@router.delete("/customers/{cid}")
def delete_customer(cid: int, user: dict = Depends(require_perm("customer:delete"))):
    if query_one("SELECT 1 FROM wms_outbound_order WHERE customer_id=%s LIMIT 1", (cid,)):
        return fail("该客户存在出库单记录，无法删除")
    execute("DELETE FROM wms_customer WHERE id=%s", (cid,))
    add_log(None, user, "客户管理", "删除", f"删除客户 id={cid}")
    return ok(msg="删除成功")
