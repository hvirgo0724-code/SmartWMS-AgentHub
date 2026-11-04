"""数据初始化脚本：建库建表 + 插入中等量演示数据
数据通过真实的业务服务函数（confirm_inbound/allocate_outbound/ship_outbound）生成，
保证入库单/出库单/库存/批次/库位/移库记录/质检/调整单之间的联动一致性。
运行: python seed_data.py
"""
import sys
import os
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
random.seed(42)

from config import DB_CONFIG
from database import get_conn, query, query_one, execute, execute_return_id, transaction, add_log
from security import hash_password
from services import confirm_inbound, allocate_outbound, ship_outbound, BizError
from datetime import datetime, date, timedelta

ADMIN = {"id": 1, "username": "admin", "ip": "127.0.0.1"}


def run_sql_file(path):
    """按语句拆分执行 init_db.sql（忽略注释）"""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    import pymysql
    from config import DB_CONFIG
    # init_db.sql 中库名写死为默认值，按实际配置替换
    content = content.replace("warehouse_management_system01", DB_CONFIG["database"])
    conn = pymysql.connect(host=DB_CONFIG["host"], port=DB_CONFIG["port"], user=DB_CONFIG["user"],
                           password=DB_CONFIG["password"], charset="utf8mb4")
    try:
        conn.cursor().execute(f"DROP DATABASE IF EXISTS {DB_CONFIG['database']}")
        stmts = []
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("--") or stripped.startswith("/*"):
                continue
            stmts.append(line)
        buf = ""
        for line in stmts:
            buf += line + "\n"
            if line.strip().endswith(";"):
                sql = buf.strip()
                if sql:
                    conn.cursor().execute(sql.rstrip(";"))
                buf = ""
        conn.commit()
    finally:
        conn.close()


def seed_users():
    users = [
        ("admin", "admin123", "系统管理员", "13800000001", "admin@wms.com", 1, ["admin"]),
        ("zhangwei", "123456", "张伟", "13800000002", "zhangwei@wms.com", 1, ["warehouse_keeper"]),
        ("lina", "123456", "李娜", "13800000003", "lina@wms.com", 1, ["operator"]),
        ("wangfang", "123456", "王芳", "13800000004", "wangfang@wms.com", 1, ["operator"]),
        ("liuyang", "123456", "刘洋", "13800000005", "liuyang@wms.com", 1, ["viewer"]),
    ]
    role_map = {r["role_code"]: r["id"] for r in query("SELECT * FROM sys_role")}
    for uname, pwd, name, phone, email, status, roles in users:
        uid = execute_return_id(
            "INSERT INTO sys_user (username, password_hash, real_name, phone, email, status) VALUES (%s,%s,%s,%s,%s,%s)",
            (uname, hash_password(pwd), name, phone, email, status))
        for rc in roles:
            execute("INSERT INTO sys_user_role (user_id, role_id) VALUES (%s,%s)", (uid, role_map[rc]))
    print(f"  用户 {len(users)} 条")


def seed_rbac():
    roles = [
        ("管理员", "admin", "拥有系统全部权限"),
        ("仓管员", "warehouse_keeper", "仓库作业：出入库执行、库存管理、盘点"),
        ("操作员", "operator", "日常作业：出入库操作、库存查询"),
        ("观察者", "viewer", "只读查询权限"),
    ]
    perms = [
        ("用户查看", "user:view"), ("用户新增", "user:add"), ("用户编辑", "user:edit"), ("用户删除", "user:delete"),
        ("角色查看", "role:view"), ("角色新增", "role:add"), ("角色编辑", "role:edit"), ("角色删除", "role:delete"),
        ("仓库维护", "warehouse:add"), ("库区维护", "area:add"), ("库位维护", "location:add"),
        ("商品维护", "product:add"), ("商品编辑", "product:edit"), ("商品删除", "product:delete"),
        ("供应商维护", "supplier:add"), ("供应商编辑", "supplier:edit"), ("供应商删除", "supplier:delete"),
        ("客户维护", "customer:add"), ("客户编辑", "customer:edit"), ("客户删除", "customer:delete"),
        ("入库新增", "inbound:add"), ("入库审核", "inbound:audit"), ("入库确认", "inbound:confirm"),
        ("出库新增", "outbound:add"), ("出库审核", "outbound:audit"), ("出库分配", "outbound:allocate"), ("出库发货", "outbound:ship"),
        ("库存移动", "inventory:move"), ("库存调整", "inventory:adjust"),
        ("盘点管理", "check:add"), ("智能决策", "decision:view"), ("报表查看", "report:view"),
        ("系统配置", "system:config"), ("日志查看", "log:view"),
    ]
    for name, code, desc in roles:
        execute("INSERT INTO sys_role (role_name, role_code, description) VALUES (%s,%s,%s)", (name, code, desc))
    for name, code in perms:
        execute("INSERT INTO sys_permission (perm_name, perm_code) VALUES (%s,%s)", (name, code))
    perm_ids = {p["perm_code"]: p["id"] for p in query("SELECT * FROM sys_permission")}
    role_ids = {r["role_code"]: r["id"] for r in query("SELECT * FROM sys_role")}
    grants = {
        "admin": list(perm_ids.values()),
        "warehouse_keeper": [perm_ids[c] for c in ("inbound:add", "inbound:confirm", "outbound:add", "outbound:allocate",
                                                   "outbound:ship", "inventory:move", "inventory:adjust", "check:add",
                                                   "product:add", "product:edit", "decision:view", "report:view")],
        "operator": [perm_ids[c] for c in ("inbound:add", "inbound:confirm", "outbound:add", "outbound:allocate",
                                           "outbound:ship", "inventory:move", "report:view")],
        "viewer": [perm_ids[c] for c in ("report:view", "decision:view")],
    }
    for rc, pids in grants.items():
        for pid in pids:
            execute("INSERT INTO sys_role_permission (role_id, perm_id) VALUES (%s,%s)", (role_ids[rc], pid))
    print(f"  角色 {len(roles)} / 权限 {len(perms)}")


def seed_base_data():
    # 仓库
    warehouses = [
        ("WH001", "上海中心仓", "上海市嘉定区安亭镇墨玉路88号", "normal", 12000),
        ("WH002", "苏州华东仓", "江苏省苏州市工业园区港田路99号", "normal", 8000),
        ("WH003", "广州冷链仓", "广东省广州市黄埔区开发大道201号", "cold", 5000),
    ]
    for code, name, addr, t, area in warehouses:
        execute("INSERT INTO wms_warehouse (warehouse_code, warehouse_name, address, type, area) VALUES (%s,%s,%s,%s,%s)",
                (code, name, addr, t, area))

    # 库区与库位
    area_tpl = [("A", "存储区一", "storage"), ("B", "存储区二", "storage"), ("P", "拣货区", "picking"),
                ("R", "退货区", "return"), ("C", "收货暂存区", "receiving")]
    loc_total = 0
    for wh_idx, (code, _, _, wh_type, _) in enumerate(warehouses):
        wh_id = wh_idx + 1
        for a_code, a_name, a_type in area_tpl:
            if wh_type == "cold" and a_type == "storage":
                a_name += "（温控）"
            area_code = f"{code}{a_code}"
            aid = execute_return_id(
                "INSERT INTO wms_area (warehouse_id, area_code, area_name, type, capacity) VALUES (%s,%s,%s,%s,%s)",
                (wh_id, f"{code}-Z{a_code}", a_name, a_type, 200))
            # 每个库区生成 3排×10列 = 30 个库位
            loc_type = "temp" if (wh_type == "cold" and a_type == "storage") else "normal"
            for r in range(1, 4):
                for c in range(1, 11):
                    execute("""INSERT INTO wms_location (area_id, location_code, type, max_weight, max_volume, status)
                               VALUES (%s,%s,%s,%s,%s,'empty')""",
                            (aid, f"{code}-{a_code}{r:02d}{c:02d}", loc_type, 500, 10))
                    loc_total += 1
    print(f"  仓库 3 / 库区 {len(warehouses)*len(area_tpl)} / 库位 {loc_total}")

    # 商品（50个）
    categories = {
        "数码电子": [("智能手机", "台", 0.35, 0.002, 0, 0, 2999), ("蓝牙耳机", "个", 0.05, 0.001, 0, 0, 399),
                     ("移动电源", "个", 0.25, 0.001, 0, 0, 129), ("智能手表", "块", 0.08, 0.001, 0, 0, 899),
                     ("笔记本电脑", "台", 1.8, 0.01, 0, 0, 5999), ("平板电脑", "台", 0.6, 0.003, 0, 0, 2599),
                     ("机械键盘", "把", 0.9, 0.004, 0, 0, 399), ("无线鼠标", "个", 0.1, 0.001, 0, 0, 99)],
        "食品饮料": [("牛奶礼盒", "盒", 1.2, 0.004, 30, 1, 59), ("坚果礼盒", "盒", 0.8, 0.003, 180, 1, 88),
                     ("进口咖啡豆", "袋", 0.5, 0.002, 270, 1, 79), ("橄榄油", "瓶", 0.9, 0.001, 540, 1, 129),
                     ("方便面整箱", "箱", 3.0, 0.02, 180, 1, 45), ("矿泉水整箱", "箱", 9.5, 0.02, 365, 1, 28),
                     ("巧克力礼盒", "盒", 0.4, 0.002, 90, 1, 99), ("饼干礼盒", "盒", 0.6, 0.003, 150, 1, 49)],
        "生鲜冷藏": [("冷鲜牛肉", "盒", 0.5, 0.001, 5, 1, 69), ("三文鱼刺身", "盒", 0.4, 0.001, 3, 1, 129),
                     ("鲜奶酸奶", "箱", 5.0, 0.01, 7, 1, 89), ("速冻水饺", "袋", 1.0, 0.003, 180, 1, 32),
                     ("冰淇淋家庭装", "盒", 1.5, 0.003, 90, 1, 49), ("冷冻虾仁", "袋", 0.5, 0.001, 365, 1, 78)],
        "日用百货": [("洗衣液", "桶", 1.5, 0.003, 1095, 1, 39), ("纸巾整箱", "箱", 4.0, 0.02, 1095, 1, 59),
                     ("洗洁精", "瓶", 1.0, 0.001, 1095, 1, 19), ("牙膏套装", "盒", 0.3, 0.001, 730, 1, 29),
                     ("洗发水", "瓶", 0.5, 0.001, 1095, 1, 49), ("垃圾袋", "卷", 0.2, 0.001, 0, 0, 9)],
        "服饰鞋包": [("男士T恤", "件", 0.2, 0.001, 0, 0, 79), ("牛仔裤", "条", 0.6, 0.002, 0, 0, 159),
                     ("运动鞋", "双", 0.8, 0.005, 0, 0, 299), ("双肩背包", "个", 0.7, 0.006, 0, 0, 189),
                     ("棒球帽", "顶", 0.15, 0.001, 0, 0, 45), ("羊毛围巾", "条", 0.2, 0.001, 0, 0, 129)],
        "家用电器": [("电风扇", "台", 3.5, 0.03, 0, 0, 199), ("电饭煲", "台", 3.0, 0.02, 0, 0, 299),
                     ("吸尘器", "台", 4.0, 0.03, 0, 0, 899), ("电水壶", "个", 1.2, 0.005, 0, 0, 99),
                     ("空气炸锅", "台", 4.5, 0.02, 0, 0, 399), ("加湿器", "台", 1.5, 0.006, 0, 0, 159)],
    }
    idx = 0
    for cat, items in categories.items():
        for name, unit, wt, vol, life, batch, price in items:
            idx += 1
            sku = f"SKU{idx:04d}"
            execute("""INSERT INTO wms_product (sku, barcode, product_name, category, unit, weight, volume,
                         shelf_life, is_batch_managed, min_stock, max_stock, price)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (sku, f"69{random.randint(1000000000, 9999999999)}", f"{name}-{idx:03d}", cat, unit, wt, vol,
                     life, batch, random.randint(50, 200), random.randint(800, 2000), price))
    print(f"  商品 {idx} 条")

    # 供应商 12 / 客户 12
    suppliers = [("华强电子科技", "张三"), ("美味食品有限公司", "李四"), ("鲜达冷链", "王五"), ("日用品百货集团", "赵六"),
                 ("潮流服饰", "钱七"), ("小家电商行", "孙八"), ("优质坚果食品", "周九"), ("海河乳业", "吴十"),
                 ("江南纸业", "郑一"), ("深蓝数码", "冯二"), ("绿源农业", "陈三"), ("北方粮油", "褚四")]
    for i, (name, contact) in enumerate(suppliers, 1):
        execute("""INSERT INTO wms_supplier (supplier_code, supplier_name, contact, phone, address)
                   VALUES (%s,%s,%s,%s,%s)""",
                (f"SUP{i:03d}", f"{name}有限公司", contact, f"139{random.randint(10000000, 99999999)}",
                 f"上海市闵行区莲花路{random.randint(100, 999)}号"))
    customers = [("京东自营", "东哥"), ("天猫超市", "猫小二"), ("盒马鲜生", "盒马君"), ("永辉超市", "张店长"),
                 ("大润发", "李经理"), ("苏宁易购", "王主管"), ("拼多多", "多多"), ("叮咚买菜", "叮咚"),
                 ("美团优选", "团团"), ("朴朴超市", "朴朴"), ("山姆会员店", "山姆"), ("costco", "考斯特")]
    for i, (name, contact) in enumerate(customers, 1):
        execute("""INSERT INTO wms_customer (customer_code, customer_name, contact, phone, address)
                   VALUES (%s,%s,%s,%s,%s)""",
                (f"CUS{i:03d}", f"{name}", contact, f"138{random.randint(10000000, 99999999)}",
                 f"上海市浦东新区张江路{random.randint(100, 999)}号"))
    print(f"  供应商 {len(suppliers)} / 客户 {len(customers)}")


def get_categories_products():
    cats = {}
    for p in query("SELECT * FROM wms_product"):
        cats.setdefault(p["category"], []).append(p)
    return cats


def seed_inbound_outbound(cats):
    """通过真实业务流程生成入库/出库/库存数据（联动一致）"""
    products_all = [p for plist in cats.values() for p in plist]
    cold_products = cats.get("生鲜冷藏", []) + cats.get("食品饮料", [])
    operators = ["zhangwei", "lina", "wangfang"]
    now = datetime.now()

    # ---------- 入库单：30 张（25 completed 走完整入库流程）----------
    for i in range(30):
        wh_id = 3 if i % 5 == 4 else random.choice([1, 2])  # 每5单有1单进冷链仓
        pool = cold_products if wh_id == 3 else products_all
        supplier_id = random.randint(1, 12)
        days_ago = random.randint(1, 80)
        expected = now - timedelta(days=days_ago)
        status = "completed" if i < 25 else ("approved" if i % 2 == 0 else "pending")
        init_status = "approved" if status == "completed" else status
        # 约 75% 的入库单在预计时间前后到货，便于供应商准时率演示
        actual = (expected + timedelta(hours=(-random.randint(0, 8) if random.random() < 0.75
                                                 else random.randint(6, 24))) if status == "completed" else None)
        with transaction() as conn:
            order_no = f"IN{(now - timedelta(days=days_ago)).strftime('%Y%m%d')}{i+1:03d}"
            oid = execute_return_id(
                """INSERT INTO wms_inbound_order (order_no, warehouse_id, supplier_id, status, expected_time,
                   actual_time, operator, create_time) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (order_no, wh_id, supplier_id, init_status, expected, actual,
                 random.choice(operators), expected), conn)
            # 明细 2~5 行
            picked = random.sample(pool, random.randint(2, 5))
            for p in picked:
                qty = random.randint(20, 150)
                batch_no, prod_date, exp_date = "", None, None
                if p["is_batch_managed"]:
                    prod_date = (expected - timedelta(days=random.randint(1, 30))).date()
                    batch_no = f"B{prod_date.strftime('%y%m%d')}{p['id']:03d}"
                    if p["shelf_life"]:
                        # 控制部分批次临期（用于效期预警演示）
                        if random.random() < 0.15:
                            exp_date = prod_date + timedelta(days=random.randint(3, 25))
                        else:
                            exp_date = prod_date + timedelta(days=int(p["shelf_life"] * random.uniform(0.5, 1.0)))
                execute("""INSERT INTO wms_inbound_detail (inbound_id, product_id, quantity, batch_no,
                           production_date, expiry_date) VALUES (%s,%s,%s,%s,%s,%s)""",
                        (oid, p["id"], qty, batch_no, prod_date, exp_date), conn)
        if status == "completed":
            # 用真实入库服务执行（联动库存/批次/库位/移库记录/质检）
            with transaction() as conn:
                # 时间回溯：先把单据时间写为历史，业务函数只更新状态与库存
                confirm_inbound(conn, oid, {"id": 1, "username": random.choice(operators), "ip": "seed"})
                # 回溯操作时间便于趋势图展示
                execute("UPDATE wms_inbound_order SET create_time=%s, actual_time=%s WHERE id=%s",
                        (expected, actual, oid), conn)
                execute("""UPDATE wms_stock_move SET create_time=%s WHERE ref_type='inbound'
                           AND ref_no=%s AND create_time>=DATE_SUB(NOW(), INTERVAL 1 MINUTE)""",
                        (expected + timedelta(hours=3), order_no), conn)
                execute("""UPDATE wms_inspection SET create_time=%s WHERE inbound_id=%s
                           AND create_time>=DATE_SUB(NOW(), INTERVAL 1 MINUTE)""", (expected + timedelta(hours=2), oid), conn)
    print("  入库单 30 张（25张已完成入库流程）")

    # ---------- 出库单：28 张（20 shipped 走完整出库流程）----------
    statuses = ["shipped"] * 18 + ["allocated"] * 2 + ["approved"] * 4 + ["pending"] * 4
    shipped_count = 0
    for i, status in enumerate(statuses):
        wh_id = random.choice([1, 2])
        customer_id = random.randint(1, 12)
        days_ago = random.randint(0, 60)
        expected = now - timedelta(days=days_ago)
        operator = random.choice(operators)
        with transaction() as conn:
            order_no = f"OUT{(now - timedelta(days=days_ago)).strftime('%Y%m%d')}{i+1:03d}"
            # 有库存的商品才可出库
            avail_products = query("""SELECT DISTINCT p.* FROM wms_product p JOIN wms_inventory i
                                      ON i.product_id=p.id WHERE i.warehouse_id=%s AND i.available_qty>10""", (wh_id,), conn)
            if len(avail_products) < 2:
                continue
            picked = random.sample(avail_products, random.randint(1, 4))
            oid = execute_return_id(
                """INSERT INTO wms_outbound_order (order_no, warehouse_id, customer_id, priority, status,
                   expected_time, actual_time, operator, create_time)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (order_no, wh_id, customer_id, random.choice([1, 2, 2, 3]), "pending" if status != "pending" else "pending",
                 expected, None, operator, expected), conn)
            for p in picked:
                avail = int(query_one("""SELECT COALESCE(SUM(available_qty),0) a FROM wms_inventory
                                     WHERE warehouse_id=%s AND product_id=%s AND status='normal'""", (wh_id, p["id"]), conn)["a"])
                qty = random.randint(5, max(6, min(60, avail // 3 or 1)))
                execute("INSERT INTO wms_outbound_detail (outbound_id, product_id, quantity) VALUES (%s,%s,%s)",
                        (oid, p["id"], qty), conn)

        # 走真实流程：审核 → 分配 → 发货
        try:
            if status in ("shipped", "allocated", "approved"):
                execute("UPDATE wms_outbound_order SET status='approved' WHERE id=%s", (oid,))
            if status in ("shipped", "allocated"):
                with transaction() as conn:
                    allocate_outbound(conn, oid, {"id": 1, "username": operator, "ip": "seed"})
            if status == "shipped":
                with transaction() as conn:
                    ship_outbound(conn, oid, {"id": 1, "username": operator, "ip": "seed"})
                    shipped_count += 1
                    execute("UPDATE wms_outbound_order SET actual_time=%s WHERE id=%s",
                            (expected + timedelta(hours=random.randint(1, 8)), oid), conn)
                    execute("""UPDATE wms_stock_move SET create_time=%s WHERE ref_type='outbound'
                               AND ref_no=%s AND create_time>=DATE_SUB(NOW(), INTERVAL 1 MINUTE)""",
                            (expected + timedelta(hours=5), order_no), conn)
        except BizError as e:
            # 库存不足时回退为 pending（演示数据容错）
            execute("UPDATE wms_outbound_order SET status='pending' WHERE id=%s", (oid,))
            execute("DELETE FROM wms_outbound_detail WHERE outbound_id=%s", (oid,))
            execute("DELETE FROM wms_outbound_order WHERE id=%s", (oid,))
    print(f"  出库单 28 张（{shipped_count} 张已完成发货流程）")

    # ---------- 波次：将 2 张 approved 单组成一个波次并演示拣货 ----------
    approved = query("SELECT * FROM wms_outbound_order WHERE status='approved' LIMIT 2")
    if len(approved) >= 2:
        with transaction() as conn:
            wave_no = f"WV{now.strftime('%Y%m%d')}001"
            vid = execute_return_id(
                """INSERT INTO wms_wave (wave_no, warehouse_id, strategy, status, order_count, operator)
                   VALUES (%s,%s,'product','pending',%s,%s)""",
                (wave_no, approved[0]["warehouse_id"], len(approved), "admin"), conn)
            for o in approved:
                execute("UPDATE wms_outbound_order SET wave_id=%s WHERE id=%s", (vid, o["id"]), conn)
            for o in approved:
                allocate_outbound(conn, o["id"], {"id": 1, "username": "zhangwei", "ip": "seed"})
            execute("UPDATE wms_wave SET status='pending' WHERE id=%s", (vid,), conn)
    print("  波次 1 个（含2张已分配订单）")


def seed_check_adjust():
    """盘点单：1张已完成（带差异）、1张盘点中"""
    now = datetime.now()
    wh_id = 1
    invs = query("""SELECT i.* FROM wms_inventory i WHERE i.warehouse_id=%s AND i.quantity>0
                    ORDER BY i.id LIMIT 12""", (wh_id,))
    if not invs:
        return
    # 已完成盘点（8条，2条差异）
    with transaction() as conn:
        check_no = f"CK{(now - timedelta(days=15)).strftime('%Y%m%d')}001"
        cid = execute_return_id(
            """INSERT INTO wms_check_order (check_no, warehouse_id, type, blind, status, operator,
               start_time, end_time, create_time) VALUES (%s,%s,'cycle',0,'completed','zhangwei',%s,%s,%s)""",
            (check_no, wh_id, now - timedelta(days=15), now - timedelta(days=15, hours=-2), now - timedelta(days=15)), conn)
        for i, inv in enumerate(invs[:8]):
            actual = inv["quantity"]
            if i == 2:
                actual = inv["quantity"] - 5  # 盘亏
            elif i == 5:
                actual = inv["quantity"] + 3  # 盘盈
            from services import submit_check
            # 直接写入明细（历史单据，不再触发库存联动，保持当前库存状态）
            execute("""INSERT INTO wms_check_detail (check_id, location_id, product_id, batch_no, book_qty, actual_qty, diff_qty)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (cid, inv["location_id"], inv["product_id"], inv["batch_no"], inv["quantity"], actual, actual - inv["quantity"]), conn)
            diff = actual - inv["quantity"]
            if diff != 0:
                execute("""INSERT INTO wms_adjustment (adjust_no, warehouse_id, product_id, batch_no, location_id,
                           before_qty, after_qty, diff_qty, reason, operator, create_time)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'lina',%s)""",
                        (f"ADJ{now.strftime('%Y%m%d')}{i:03d}", wh_id, inv["product_id"], inv["batch_no"],
                         inv["location_id"], inv["quantity"], actual, diff, "surplus" if diff > 0 else "loss",
                         now - timedelta(days=15)))
    # 盘点中
    with transaction() as conn:
        check_no = f"CK{now.strftime('%Y%m%d')}002"
        cid2 = execute_return_id(
            """INSERT INTO wms_check_order (check_no, warehouse_id, type, blind, status, operator, start_time)
               VALUES (%s,%s,'cycle',1,'checking','lina',%s)""",
            (check_no, wh_id, now), conn)
        for inv in invs[8:]:
            execute("""INSERT INTO wms_check_detail (check_id, location_id, product_id, batch_no, book_qty)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (cid2, inv["location_id"], inv["product_id"], inv["batch_no"], inv["quantity"]), conn)
    print("  盘点单 2 张（1完成带差异调整 / 1盘点中）")

    # 库存移动记录：几条历史移动
    moves = query("SELECT * FROM wms_inventory WHERE warehouse_id=1 AND quantity>0 LIMIT 5")
    for i, inv in enumerate(moves):
        with transaction() as conn:
            mvid = execute_return_id(
                """INSERT INTO wms_stock_move (move_type, warehouse_id, from_location_id, to_location_id,
                   product_id, batch_no, quantity, ref_type, ref_no, operator, create_time)
                   VALUES ('move',%s,%s,%s,%s,%s,%s,'move','','wangfang',%s)""",
                (inv["warehouse_id"], inv["location_id"], inv["location_id"], inv["product_id"], inv["batch_no"],
                 max(1, inv["quantity"] // 10), now - timedelta(days=random.randint(1, 10))), conn)
    print("  历史移库记录若干")

    # 冻结一条库存演示
    inv = query_one("SELECT * FROM wms_inventory WHERE quantity>0 ORDER BY id DESC")
    if inv:
        execute("UPDATE wms_inventory SET status='frozen' WHERE id=%s", (inv["id"],))
        print(f"  冻结库存演示 id={inv['id']}")


def seed_asns():
    """供应商预约送货演示数据：待收货 ASN 可直接转入库单"""
    now = datetime.now()
    suppliers = query("SELECT * FROM wms_supplier ORDER BY id LIMIT 4")
    warehouses = query("SELECT * FROM wms_warehouse ORDER BY id")
    products = query("SELECT * FROM wms_product ORDER BY id LIMIT 12")
    statuses = ["pending", "pending", "received", "pending", "cancelled"]
    for i, status in enumerate(statuses):
        supplier = suppliers[i % len(suppliers)]
        wh = warehouses[i % len(warehouses)]
        asn_no = f"ASN{now.strftime('%Y%m%d')}{i + 1:03d}"
        with transaction() as conn:
            aid = execute_return_id(
                """INSERT INTO wms_asn (asn_no, warehouse_id, supplier_id, expected_time, status, remark, operator)
                   VALUES (%s,%s,%s,%s,%s,%s,'zhangwei')""",
                (asn_no, wh["id"], supplier["id"], now + timedelta(days=i - 1), status,
                 "演示数据：供应商预约送货"), conn)
            for p in products[i * 2:i * 2 + 2]:
                execute("INSERT INTO wms_asn_detail (asn_id, product_id, quantity) VALUES (%s,%s,%s)",
                        (aid, p["id"], random.randint(30, 200)), conn)
    print(f"  收货通知 ASN {len(statuses)} 张（{statuses.count('pending')} 张待收货）")


def seed_decision_config():
    rules = [
        ("缺货预警", "low_stock", 0, 1),
        ("超储预警", "over_stock", 0, 1),
        ("临期预警", "expiry", 30, 1),
        ("滞销预警", "dead_stock", 90, 1),
    ]
    for name, t, threshold, enabled in rules:
        execute("INSERT INTO wms_alert_rule (rule_name, rule_type, threshold, enabled) VALUES (%s,%s,%s,%s)",
                (name, t, threshold, enabled))

    configs = [
        ("batch_management_enabled", "1", "是否启用批次管理"),
        ("default_putaway_strategy", "same_product_first", "默认上架策略（同商品优先）"),
        ("outbound_strategy", "FIFO", "默认出库策略（先进先出）"),
        ("expiry_alert_days", "30", "临期预警天数"),
        ("auto_wave_enabled", "1", "是否启用自动波次"),
        ("company_name", "智联云仓科技有限公司", "企业名称"),
    ]
    for k, v, d in configs:
        execute("INSERT INTO sys_config (config_key, config_value, description) VALUES (%s,%s,%s)", (k, v, d))
    print("  预警规则 4 / 系统参数 6")


def main():
    print("=" * 50)
    print("开始初始化数据库...")
    sql_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "init_db.sql")
    run_sql_file(sql_path)
    print("[1/5] 建库建表完成")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"USE {DB_CONFIG['database']}")

    print("[2/5] 写入基础数据")
    seed_rbac()
    seed_users()
    seed_base_data()
    cats = get_categories_products()

    print("[3/5] 生成业务数据（入库/出库/库存联动）")
    seed_inbound_outbound(cats)
    seed_asns()

    print("[4/5] 生成盘点/调整/移动数据")
    seed_check_adjust()

    print("[5/5] 写入智能决策与系统配置")
    seed_decision_config()

    # 统计
    stats = {}
    for t in ["sys_user", "sys_role", "sys_permission", "wms_warehouse", "wms_area", "wms_location",
              "wms_product", "wms_supplier", "wms_customer", "wms_asn", "wms_asn_detail",
              "wms_inbound_order", "wms_inbound_detail",
              "wms_outbound_order", "wms_outbound_detail", "wms_inventory", "wms_batch", "wms_stock_move",
              "wms_inspection", "wms_adjustment", "wms_check_order", "wms_check_detail", "wms_wave",
              "wms_alert_rule", "sys_config"]:
        stats[t] = query_one(f"SELECT COUNT(*) c FROM {t}")["c"]
    print("=" * 50)
    print("数据初始化完成！统计：")
    for k, v in stats.items():
        print(f"  {k:28s} {v}")
    print("=" * 50)
    print("管理员账号: admin / admin123")


if __name__ == "__main__":
    main()
