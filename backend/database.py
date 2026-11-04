"""数据库连接与 SQL 工具（PyMySQL 原生 SQL）"""
import pymysql
from contextlib import contextmanager
from config import DB_CONFIG


@contextmanager
def get_conn(autocommit=True):
    conn = pymysql.connect(
        host=DB_CONFIG["host"], port=DB_CONFIG["port"], user=DB_CONFIG["user"],
        password=DB_CONFIG["password"], database=DB_CONFIG["database"],
        charset=DB_CONFIG["charset"], cursorclass=pymysql.cursors.DictCursor,
        autocommit=autocommit,
    )
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction():
    """事务：with transaction() as conn: conn.cursor().execute(...); 成功自动 commit，异常 rollback"""
    with get_conn(autocommit=False) as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def query(sql, params=None, conn=None):
    """查询返回 dict 列表"""
    if conn is not None:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        rows = cur.fetchall()
        cur.close()
        return rows
    with get_conn() as c:
        return query(sql, params, c)


def query_one(sql, params=None, conn=None):
    rows = query(sql, params, conn)
    return rows[0] if rows else None


def execute(sql, params=None, conn=None):
    """执行写操作，返回受影响行数"""
    if conn is not None:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        affected = cur.rowcount
        cur.close()
        return affected
    with get_conn() as c:
        return execute(sql, params, c)


def execute_return_id(sql, params=None, conn=None):
    """执行写操作并返回自增ID"""
    if conn is not None:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        new_id = cur.lastrowid
        cur.close()
        return new_id
    with get_conn() as c:
        return execute_return_id(sql, params, c)


def add_log(conn, user, module, action, detail=""):
    """记录操作日志（传入事务连接则随事务写入，否则单独写）"""
    sql = "INSERT INTO sys_log (user_id, username, module, action, detail, ip) VALUES (%s,%s,%s,%s,%s,%s)"
    params = (user.get("id"), user.get("username"), module, action, detail[:500], user.get("ip", ""))
    if conn is not None:
        return execute_return_id(sql, params, conn)
    return execute_return_id(sql, params)
