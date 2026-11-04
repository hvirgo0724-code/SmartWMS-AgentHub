"""启动引导：增量建表、索引、权限与内置知识库（幂等，可在已有数据库上安全执行）"""
import sys

from config import PARTNER_API_KEY
from database import query, query_one, execute, execute_return_id
from agents import retriever
from agents.kb_seed import KB_DOCS

CS_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS kb_document (
      id INT AUTO_INCREMENT PRIMARY KEY,
      doc_no VARCHAR(50) NOT NULL UNIQUE,
      title VARCHAR(200) NOT NULL,
      category VARCHAR(50) NOT NULL DEFAULT '通用',
      tags VARCHAR(200) DEFAULT '',
      source VARCHAR(100) DEFAULT '系统内置',
      content LONGTEXT NOT NULL,
      status VARCHAR(20) NOT NULL DEFAULT 'published' COMMENT 'draft草稿/published已发布/archived归档',
      version INT DEFAULT 1,
      chunk_count INT DEFAULT 0,
      update_by VARCHAR(50) DEFAULT '',
      create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
      update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      INDEX idx_kb_status (status),
      INDEX idx_kb_category (category)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS kb_chunk (
      id INT AUTO_INCREMENT PRIMARY KEY,
      doc_id INT NOT NULL,
      chunk_index INT NOT NULL DEFAULT 0,
      content TEXT NOT NULL,
      token_count INT DEFAULT 0,
      embedding MEDIUMTEXT,
      create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
      INDEX idx_chunk_doc (doc_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS cs_session (
      id INT AUTO_INCREMENT PRIMARY KEY,
      session_no VARCHAR(50) NOT NULL UNIQUE,
      user_id INT NOT NULL,
      username VARCHAR(50) DEFAULT '',
      channel VARCHAR(20) DEFAULT 'web',
      title VARCHAR(200) DEFAULT '新会话',
      status VARCHAR(20) DEFAULT 'active',
      message_count INT DEFAULT 0,
      last_intent VARCHAR(30) DEFAULT '',
      last_agent VARCHAR(30) DEFAULT '',
      human_agent VARCHAR(50) DEFAULT '' COMMENT '当前接入的人工坐席',
      handoff_at DATETIME DEFAULT NULL COMMENT '转人工时间',
      satisfaction INT DEFAULT 0,
      create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
      update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      INDEX idx_cs_user (user_id),
      INDEX idx_cs_time (create_time)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS cs_message (
      id INT AUTO_INCREMENT PRIMARY KEY,
      session_id INT NOT NULL,
      role VARCHAR(20) NOT NULL COMMENT 'user/assistant/agent/system',
      content LONGTEXT NOT NULL,
      agent VARCHAR(30) DEFAULT '',
      sender_name VARCHAR(50) DEFAULT '' COMMENT '人工坐席姓名',
      citations LONGTEXT,
      tool_results LONGTEXT,
      suggestions TEXT,
      confidence DECIMAL(4,3) DEFAULT NULL,
      latency_ms INT DEFAULT 0,
      llm_used TINYINT DEFAULT 0,
      feedback TINYINT DEFAULT 0 COMMENT '1赞 -1踩',
      feedback_comment VARCHAR(500) DEFAULT '',
      create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
      INDEX idx_msg_session (session_id),
      INDEX idx_msg_time (create_time)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS cs_ticket (
      id INT AUTO_INCREMENT PRIMARY KEY,
      ticket_no VARCHAR(50) NOT NULL UNIQUE,
      session_id INT,
      user_id INT NOT NULL,
      username VARCHAR(50) DEFAULT '',
      category VARCHAR(30) DEFAULT '咨询',
      priority VARCHAR(20) DEFAULT 'normal' COMMENT 'high/normal/low',
      title VARCHAR(200) NOT NULL,
      content TEXT,
      status VARCHAR(20) DEFAULT 'open' COMMENT 'open/processing/resolved/closed',
      assignee VARCHAR(50) DEFAULT '',
      resolution TEXT,
      create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
      update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      INDEX idx_ticket_status (status),
      INDEX idx_ticket_user (user_id),
      INDEX idx_ticket_session (session_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS cs_agent_log (
      id INT AUTO_INCREMENT PRIMARY KEY,
      session_id INT,
      message_id INT,
      agent VARCHAR(50),
      action VARCHAR(50),
      detail VARCHAR(500),
      status VARCHAR(20) DEFAULT 'done',
      latency_ms INT DEFAULT 0,
      create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
      INDEX idx_agent_session (session_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS wms_scan_log (
      id INT AUTO_INCREMENT PRIMARY KEY,
      code VARCHAR(120) NOT NULL,
      scan_type VARCHAR(20) DEFAULT 'unknown' COMMENT 'product/location/inbound/outbound/asn/wave/move/unknown',
      ref_id INT DEFAULT NULL,
      ref_no VARCHAR(80) DEFAULT '',
      action VARCHAR(30) DEFAULT 'scan' COMMENT 'resolve/move/confirm/ship/to_inbound/pick',
      result VARCHAR(20) DEFAULT 'success',
      operator VARCHAR(50) DEFAULT '',
      create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
      INDEX idx_scan_time (create_time),
      INDEX idx_scan_code (code),
      INDEX idx_scan_operator (operator)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]

NEW_PERMS = [
    ("智能客服使用", "cs:view"),
    ("知识库管理", "cs:kb"),
    ("工单处理", "cs:ticket"),
    ("扫码作业", "scan:view"),
]

ROLE_GRANTS = {
    "admin": ["cs:view", "cs:kb", "cs:ticket", "scan:view"],
    "warehouse_keeper": ["cs:view", "cs:ticket", "scan:view"],
    "operator": ["cs:view", "scan:view"],
    "viewer": ["cs:view", "scan:view"],
}

INDEXES = [
    ("wms_product", "idx_product_supplier", "supplier_id"),
    ("wms_inventory", "idx_inv_avail", "warehouse_id, product_id, available_qty"),
    ("wms_inventory", "idx_inv_product_wh", "product_id, warehouse_id"),
    ("wms_stock_move", "idx_move_type_time", "move_type, create_time"),
    ("wms_stock_move", "idx_move_product_time", "product_id, create_time"),
    ("wms_inbound_order", "idx_inbound_supplier", "supplier_id"),
    ("wms_inbound_order", "idx_inbound_time", "create_time"),
    ("wms_outbound_order", "idx_outbound_customer", "customer_id"),
    ("wms_outbound_order", "idx_outbound_time", "create_time"),
    ("wms_asn", "idx_asn_supplier", "supplier_id"),
    ("wms_asn", "idx_asn_status", "status"),
    ("wms_batch", "idx_batch_supplier", "supplier_id"),
    ("wms_alert_log", "idx_alert_type_time", "alert_type, create_time"),
    ("wms_replenishment", "idx_replenish_status", "status"),
    ("sys_log", "idx_log_user", "username"),
    ("cs_ticket", "idx_ticket_session", "session_id"),
]


def _column_exists(table, column):
    return query_one("""SELECT 1 FROM information_schema.columns
                        WHERE table_schema=DATABASE() AND table_name=%s AND column_name=%s""",
                     (table, column))


def _index_exists(table, name):
    return query_one("""SELECT 1 FROM information_schema.statistics
                        WHERE table_schema=DATABASE() AND table_name=%s AND index_name=%s""",
                     (table, name))


def _ensure_column(table, column, ddl):
    if not _column_exists(table, column):
        execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _ensure_index(table, name, columns):
    if not _index_exists(table, name):
        execute(f"ALTER TABLE {table} ADD INDEX {name} ({columns})")


def _seed_permissions():
    for name, code in NEW_PERMS:
        row = query_one("SELECT id FROM sys_permission WHERE perm_code=%s", (code,))
        if not row:
            execute("INSERT INTO sys_permission (perm_name, perm_code) VALUES (%s,%s)", (name, code))
    roles = {r["role_code"]: r["id"] for r in query("SELECT id, role_code FROM sys_role")}
    perms = {p["perm_code"]: p["id"] for p in query("SELECT id, perm_code FROM sys_permission")}
    for role_code, codes in ROLE_GRANTS.items():
        rid = roles.get(role_code)
        if not rid:
            continue
        for code in codes:
            pid = perms.get(code)
            if pid:
                execute("INSERT IGNORE INTO sys_role_permission (role_id, perm_id) VALUES (%s,%s)", (rid, pid))
    # 新增权限统一授予管理员
    admin_id = roles.get("admin")
    if admin_id:
        for pid in perms.values():
            execute("INSERT IGNORE INTO sys_role_permission (role_id, perm_id) VALUES (%s,%s)", (admin_id, pid))


def _seed_configs():
    defaults = [
        ("partner_api_key", PARTNER_API_KEY, "供应商开放接口密钥（请求头 X-Partner-Key）"),
        ("cs_sla_high_hours", "2", "高优先级工单响应时限（小时）"),
        ("cs_sla_normal_hours", "8", "普通工单响应时限（小时）"),
        ("cs_llm_enabled", "auto", "智能客服大模型模式：auto/off"),
        ("llm_base", "", "OpenAI 兼容大模型接口地址，如 https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ("llm_key", "", "大模型 API Key（仅管理员可配置）"),
        ("llm_model", "qwen-plus", "大模型名称，如 qwen-plus / deepseek-chat / gpt-4o-mini"),
        ("llm_timeout", "30", "大模型调用超时（秒）"),
    ]
    for key, value, desc in defaults:
        if not query_one("SELECT id FROM sys_config WHERE config_key=%s", (key,)):
            execute("INSERT INTO sys_config (config_key, config_value, description) VALUES (%s,%s,%s)",
                    (key, value, desc))


def _backfill_product_supplier():
    """按最近入库单 / 批次补齐商品默认供应商，便于补货清单直接按供应商汇总"""
    sqls = [
        """UPDATE wms_product p
           JOIN (SELECT d.product_id,
                        SUBSTRING_INDEX(GROUP_CONCAT(o.supplier_id ORDER BY o.id DESC), ',', 1) sid
                 FROM wms_inbound_detail d JOIN wms_inbound_order o ON d.inbound_id=o.id
                 WHERE o.supplier_id IS NOT NULL GROUP BY d.product_id) t
             ON p.id=t.product_id
           SET p.supplier_id=t.sid WHERE p.supplier_id IS NULL""",
        """UPDATE wms_product p
           JOIN (SELECT b.product_id,
                        SUBSTRING_INDEX(GROUP_CONCAT(b.supplier_id ORDER BY b.id DESC), ',', 1) sid
                 FROM wms_batch b WHERE b.supplier_id IS NOT NULL GROUP BY b.product_id) t
             ON p.id=t.product_id
           SET p.supplier_id=t.sid WHERE p.supplier_id IS NULL""",
    ]
    for sql in sqls:
        try:
            execute(sql)
        except Exception as e:
            print(f"[cs][bootstrap] 商品默认供应商回填跳过: {e}")


def seed_knowledge(force=False):
    """逐篇幂等写入内置知识库并建立索引"""
    added = 0
    for doc in KB_DOCS:
        try:
            row = query_one("SELECT id, status FROM kb_document WHERE doc_no=%s", (doc["doc_no"],))
            if row:
                if force:
                    execute("""UPDATE kb_document SET title=%s, category=%s, tags=%s, content=%s,
                               status='published', update_time=NOW() WHERE id=%s""",
                            (doc["title"], doc["category"], doc["tags"], doc["content"], row["id"]))
                    retriever.ingest_document(row["id"], doc["title"], doc["content"])
                continue
            doc_id = execute_return_id("""INSERT INTO kb_document
                (doc_no, title, category, tags, source, content, status, version, update_by)
                VALUES (%s,%s,%s,%s,%s,%s,'published',1,'system')""",
                (doc["doc_no"], doc["title"], doc["category"], doc["tags"], "系统内置", doc["content"]))
            retriever.ingest_document(doc_id, doc["title"], doc["content"])
            added += 1
        except Exception as e:
            print(f"[cs][bootstrap] 知识库写入失败 {doc['doc_no']}: {e}")
    if added:
        print(f"[cs][bootstrap] 已初始化知识库文档 {added} 篇")
    return added


def ensure_cs_schema():
    """在应用启动时调用：所有步骤幂等，失败不影响主业务"""
    for ddl in CS_TABLES:
        execute(ddl)
    _ensure_column("wms_product", "supplier_id", "supplier_id INT DEFAULT NULL COMMENT '默认供应商'")
    _ensure_column("cs_session", "human_agent", "human_agent VARCHAR(50) DEFAULT '' COMMENT '当前接入的人工坐席'")
    _ensure_column("cs_session", "handoff_at", "handoff_at DATETIME DEFAULT NULL COMMENT '转人工时间'")
    _ensure_column("cs_message", "sender_name", "sender_name VARCHAR(50) DEFAULT '' COMMENT '人工坐席姓名'")
    for table, name, cols in INDEXES:
        try:
            _ensure_index(table, name, cols)
        except Exception as e:
            print(f"[cs][bootstrap] 索引 {name} 跳过: {e}")
    _seed_permissions()
    _seed_configs()
    _backfill_product_supplier()
    seed_knowledge()
    return {"kb": retriever.kb_stats()}


if __name__ == "__main__":
    try:
        print(ensure_cs_schema())
    except Exception as exc:
        print(f"初始化失败: {exc}")
        sys.exit(1)
