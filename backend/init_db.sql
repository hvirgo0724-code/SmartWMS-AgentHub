-- 智能仓储管理系统 数据库初始化脚本
-- MySQL 8.0 / utf8mb4 / InnoDB

CREATE DATABASE IF NOT EXISTS warehouse_management_system01
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE warehouse_management_system01;

-- ============ 系统管理 ============
CREATE TABLE IF NOT EXISTS sys_user (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(50) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  real_name VARCHAR(50),
  phone VARCHAR(20),
  id_card VARCHAR(18) DEFAULT NULL COMMENT '身份证号',
  email VARCHAR(100),
  status TINYINT DEFAULT 1 COMMENT '1启用 0禁用',
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sys_role (
  id INT AUTO_INCREMENT PRIMARY KEY,
  role_name VARCHAR(50) NOT NULL,
  role_code VARCHAR(50) NOT NULL UNIQUE,
  description VARCHAR(200),
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sys_permission (
  id INT AUTO_INCREMENT PRIMARY KEY,
  perm_name VARCHAR(50) NOT NULL,
  perm_code VARCHAR(50) NOT NULL UNIQUE,
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sys_user_role (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  role_id INT NOT NULL,
  UNIQUE KEY uk_user_role (user_id, role_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sys_role_permission (
  id INT AUTO_INCREMENT PRIMARY KEY,
  role_id INT NOT NULL,
  perm_id INT NOT NULL,
  UNIQUE KEY uk_role_perm (role_id, perm_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sys_config (
  id INT AUTO_INCREMENT PRIMARY KEY,
  config_key VARCHAR(100) NOT NULL UNIQUE,
  config_value VARCHAR(500),
  description VARCHAR(200),
  update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sys_log (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT,
  username VARCHAR(50),
  module VARCHAR(50),
  action VARCHAR(50),
  detail VARCHAR(500),
  ip VARCHAR(50),
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_log_time (create_time),
  INDEX idx_log_user (username)
) ENGINE=InnoDB;

-- ============ 基础数据 ============
CREATE TABLE IF NOT EXISTS wms_warehouse (
  id INT AUTO_INCREMENT PRIMARY KEY,
  warehouse_code VARCHAR(50) NOT NULL UNIQUE,
  warehouse_name VARCHAR(100) NOT NULL,
  address VARCHAR(200),
  type VARCHAR(20) COMMENT 'normal常温/cold冷藏/hazard危品',
  area DECIMAL(10,2) COMMENT '面积(平方米)',
  status TINYINT DEFAULT 1,
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS wms_area (
  id INT AUTO_INCREMENT PRIMARY KEY,
  warehouse_id INT NOT NULL,
  area_code VARCHAR(50) NOT NULL UNIQUE,
  area_name VARCHAR(100) NOT NULL,
  type VARCHAR(20) COMMENT 'storage存储/picking拣货/return退货/receiving收货',
  capacity INT DEFAULT 0,
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_area_wh (warehouse_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS wms_location (
  id INT AUTO_INCREMENT PRIMARY KEY,
  area_id INT NOT NULL,
  location_code VARCHAR(50) NOT NULL UNIQUE,
  type VARCHAR(20) COMMENT 'normal普通/heavy重型/temp温控',
  max_weight DECIMAL(10,2),
  max_volume DECIMAL(10,2),
  status VARCHAR(20) DEFAULT 'empty' COMMENT 'empty空闲/occupied占用/locked锁定',
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_loc_area (area_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS wms_product (
  id INT AUTO_INCREMENT PRIMARY KEY,
  sku VARCHAR(50) NOT NULL UNIQUE,
  barcode VARCHAR(50),
  product_name VARCHAR(100) NOT NULL,
  category VARCHAR(50),
  unit VARCHAR(20),
  weight DECIMAL(10,3),
  volume DECIMAL(10,4),
  shelf_life INT COMMENT '保质期(天), 0为不限',
  is_batch_managed TINYINT DEFAULT 1,
  min_stock INT DEFAULT 0 COMMENT '安全库存',
  max_stock INT DEFAULT 0 COMMENT '库存上限',
  price DECIMAL(10,2) DEFAULT 0,
  supplier_id INT DEFAULT NULL COMMENT '默认供应商',
  status TINYINT DEFAULT 1,
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_product_name (product_name),
  INDEX idx_product_supplier (supplier_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS wms_supplier (
  id INT AUTO_INCREMENT PRIMARY KEY,
  supplier_code VARCHAR(50) NOT NULL UNIQUE,
  supplier_name VARCHAR(100) NOT NULL,
  contact VARCHAR(50),
  phone VARCHAR(20),
  address VARCHAR(200),
  status TINYINT DEFAULT 1,
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS wms_customer (
  id INT AUTO_INCREMENT PRIMARY KEY,
  customer_code VARCHAR(50) NOT NULL UNIQUE,
  customer_name VARCHAR(100) NOT NULL,
  contact VARCHAR(50),
  phone VARCHAR(20),
  address VARCHAR(200),
  status TINYINT DEFAULT 1,
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS wms_batch (
  id INT AUTO_INCREMENT PRIMARY KEY,
  product_id INT NOT NULL,
  batch_no VARCHAR(50) NOT NULL,
  production_date DATE,
  expiry_date DATE,
  supplier_id INT,
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_batch_product (product_id),
  INDEX idx_batch_expiry (expiry_date),
  INDEX idx_batch_supplier (supplier_id)
) ENGINE=InnoDB;

-- ============ 入库管理 ============
CREATE TABLE IF NOT EXISTS wms_asn (
  id INT AUTO_INCREMENT PRIMARY KEY,
  asn_no VARCHAR(50) NOT NULL UNIQUE,
  warehouse_id INT NOT NULL,
  supplier_id INT,
  expected_time DATETIME,
  status VARCHAR(20) DEFAULT 'pending' COMMENT 'pending待收货/received已收货/cancelled',
  remark VARCHAR(500),
  operator VARCHAR(50),
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_asn_supplier (supplier_id),
  INDEX idx_asn_status (status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS wms_asn_detail (
  id INT AUTO_INCREMENT PRIMARY KEY,
  asn_id INT NOT NULL,
  product_id INT NOT NULL,
  quantity INT NOT NULL,
  INDEX idx_asn_d (asn_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS wms_inbound_order (
  id INT AUTO_INCREMENT PRIMARY KEY,
  order_no VARCHAR(50) NOT NULL UNIQUE,
  warehouse_id INT NOT NULL,
  supplier_id INT,
  asn_id INT,
  status VARCHAR(20) DEFAULT 'pending' COMMENT 'pending待审核/approved待收货/completed已入库/cancelled',
  expected_time DATETIME,
  actual_time DATETIME,
  operator VARCHAR(50),
  remark VARCHAR(500),
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_inbound_status (status),
  INDEX idx_inbound_supplier (supplier_id),
  INDEX idx_inbound_time (create_time)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS wms_inbound_detail (
  id INT AUTO_INCREMENT PRIMARY KEY,
  inbound_id INT NOT NULL,
  product_id INT NOT NULL,
  quantity INT NOT NULL,
  received_qty INT DEFAULT 0,
  batch_no VARCHAR(50),
  production_date DATE,
  expiry_date DATE,
  location_id INT,
  INDEX idx_inbound_d (inbound_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS wms_inspection (
  id INT AUTO_INCREMENT PRIMARY KEY,
  inspection_no VARCHAR(50) NOT NULL UNIQUE,
  inbound_id INT,
  product_id INT NOT NULL,
  quantity INT,
  qualified_qty INT DEFAULT 0,
  unqualified_qty INT DEFAULT 0,
  result VARCHAR(20) COMMENT 'pass合格/unqualified不合格/partial部分合格',
  inspector VARCHAR(50),
  remark VARCHAR(500),
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ============ 出库管理 ============
CREATE TABLE IF NOT EXISTS wms_outbound_order (
  id INT AUTO_INCREMENT PRIMARY KEY,
  order_no VARCHAR(50) NOT NULL UNIQUE,
  warehouse_id INT NOT NULL,
  customer_id INT,
  wave_id INT,
  priority INT DEFAULT 2 COMMENT '1紧急 2普通 3低',
  status VARCHAR(20) DEFAULT 'pending' COMMENT 'pending待审核/approved待分配/allocated已分配/picked已拣货/shipped已发货/cancelled',
  expected_time DATETIME,
  actual_time DATETIME,
  operator VARCHAR(50),
  remark VARCHAR(500),
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_outbound_status (status),
  INDEX idx_outbound_customer (customer_id),
  INDEX idx_outbound_time (create_time)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS wms_outbound_detail (
  id INT AUTO_INCREMENT PRIMARY KEY,
  outbound_id INT NOT NULL,
  product_id INT NOT NULL,
  quantity INT NOT NULL,
  picked_qty INT DEFAULT 0,
  batch_no VARCHAR(50),
  location_id INT,
  INDEX idx_outbound_d (outbound_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS wms_wave (
  id INT AUTO_INCREMENT PRIMARY KEY,
  wave_no VARCHAR(50) NOT NULL UNIQUE,
  warehouse_id INT NOT NULL,
  strategy VARCHAR(30) DEFAULT 'order' COMMENT 'order按订单/product按商品',
  status VARCHAR(20) DEFAULT 'pending' COMMENT 'pending待拣货/picked已拣货/cancelled',
  order_count INT DEFAULT 0,
  operator VARCHAR(50),
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS wms_allocation (
  id INT AUTO_INCREMENT PRIMARY KEY,
  outbound_id INT NOT NULL,
  outbound_detail_id INT NOT NULL,
  inventory_id INT NOT NULL,
  product_id INT NOT NULL,
  location_id INT NOT NULL,
  batch_no VARCHAR(50) DEFAULT '',
  quantity INT NOT NULL,
  INDEX idx_alloc_outbound (outbound_id)
) ENGINE=InnoDB;

-- ============ 库存管理 ============
CREATE TABLE IF NOT EXISTS wms_inventory (
  id INT AUTO_INCREMENT PRIMARY KEY,
  warehouse_id INT NOT NULL,
  location_id INT NOT NULL,
  product_id INT NOT NULL,
  batch_no VARCHAR(50) DEFAULT '',
  quantity INT NOT NULL DEFAULT 0,
  locked_qty INT NOT NULL DEFAULT 0,
  available_qty INT NOT NULL DEFAULT 0,
  status VARCHAR(20) DEFAULT 'normal' COMMENT 'normal正常/frozen冻结',
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_inv (warehouse_id, location_id, product_id, batch_no),
  INDEX idx_inv_product (product_id),
  INDEX idx_inv_avail (warehouse_id, product_id, available_qty),
  INDEX idx_inv_product_wh (product_id, warehouse_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS wms_stock_move (
  id INT AUTO_INCREMENT PRIMARY KEY,
  move_type VARCHAR(20) COMMENT 'inbound入库/outbound出库/move移动/adjust调整/check盘点',
  warehouse_id INT,
  from_location_id INT,
  to_location_id INT,
  product_id INT NOT NULL,
  batch_no VARCHAR(50),
  quantity INT NOT NULL,
  ref_type VARCHAR(30),
  ref_no VARCHAR(50),
  operator VARCHAR(50),
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_move_time (create_time),
  INDEX idx_move_type_time (move_type, create_time),
  INDEX idx_move_product_time (product_id, create_time)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS wms_adjustment (
  id INT AUTO_INCREMENT PRIMARY KEY,
  adjust_no VARCHAR(50) NOT NULL UNIQUE,
  warehouse_id INT NOT NULL,
  product_id INT NOT NULL,
  batch_no VARCHAR(50) DEFAULT '',
  location_id INT,
  before_qty INT,
  after_qty INT,
  diff_qty INT,
  reason VARCHAR(50) COMMENT 'check盘点/surplus盘盈/loss盘亏/damage破损/expiry过期/manual手动',
  operator VARCHAR(50),
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS wms_check_order (
  id INT AUTO_INCREMENT PRIMARY KEY,
  check_no VARCHAR(50) NOT NULL UNIQUE,
  warehouse_id INT NOT NULL,
  area_id INT,
  type VARCHAR(20) DEFAULT 'cycle' COMMENT 'cycle循环/dynamic动态/full全盘',
  blind TINYINT DEFAULT 0 COMMENT '盲盘',
  status VARCHAR(20) DEFAULT 'pending' COMMENT 'pending待盘点/checking盘点中/completed已完成',
  operator VARCHAR(50),
  start_time DATETIME,
  end_time DATETIME,
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS wms_check_detail (
  id INT AUTO_INCREMENT PRIMARY KEY,
  check_id INT NOT NULL,
  location_id INT,
  product_id INT NOT NULL,
  batch_no VARCHAR(50) DEFAULT '',
  book_qty INT DEFAULT 0,
  actual_qty INT,
  diff_qty INT,
  INDEX idx_check_d (check_id)
) ENGINE=InnoDB;

-- ============ 智能决策 ============
CREATE TABLE IF NOT EXISTS wms_alert_rule (
  id INT AUTO_INCREMENT PRIMARY KEY,
  rule_name VARCHAR(100) NOT NULL,
  rule_type VARCHAR(30) COMMENT 'low_stock缺货/over_stock超储/expiry临期/dead_stock滞销',
  threshold INT DEFAULT 0,
  enabled TINYINT DEFAULT 1,
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS wms_alert_log (
  id INT AUTO_INCREMENT PRIMARY KEY,
  rule_id INT,
  alert_type VARCHAR(30),
  level VARCHAR(10) COMMENT 'high/medium/low',
  product_id INT,
  content VARCHAR(500),
  is_read TINYINT DEFAULT 0,
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_alert_time (create_time),
  INDEX idx_alert_type_time (alert_type, create_time)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS wms_replenishment (
  id INT AUTO_INCREMENT PRIMARY KEY,
  product_id INT NOT NULL,
  current_stock INT DEFAULT 0,
  avg_daily INT DEFAULT 0,
  suggested_qty INT DEFAULT 0,
  reason VARCHAR(200),
  status VARCHAR(20) DEFAULT 'pending' COMMENT 'pending待处理/ordered已下单/ignored忽略',
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_replenish_status (status)
) ENGINE=InnoDB;

-- ============ 智能客服（RAG + 多 Agent） ============
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
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS kb_chunk (
  id INT AUTO_INCREMENT PRIMARY KEY,
  doc_id INT NOT NULL,
  chunk_index INT NOT NULL DEFAULT 0,
  content TEXT NOT NULL,
  token_count INT DEFAULT 0,
  embedding MEDIUMTEXT,
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_chunk_doc (doc_id)
) ENGINE=InnoDB;

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
) ENGINE=InnoDB;

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
) ENGINE=InnoDB;

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
) ENGINE=InnoDB;

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
) ENGINE=InnoDB;

-- ============ 扫码作业 ============
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
) ENGINE=InnoDB;
