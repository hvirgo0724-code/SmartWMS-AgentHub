"""智能客服：RAG 问答 / 会话 / 知识库 / 工单 / 供应商开放接口"""
import json
import os
import time
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import PARTNER_API_KEY
from database import query, query_one, execute, execute_return_id, transaction, add_log
from deps import get_current_user, require_perm, ok, fail
from services import gen_no, BizError
from agents import orchestrator, retriever, tools, llm
from agents.bootstrap import seed_knowledge
from agents.kb_seed import KB_DOCS

router = APIRouter(tags=["智能客服"])


# ---------- 模型 ----------
class ChatBody(BaseModel):
    session_id: Optional[int] = None
    message: str
    channel: str = "web"


class FeedbackBody(BaseModel):
    rating: int = 0
    comment: str = ""


class TicketBody(BaseModel):
    session_id: Optional[int] = None
    category: str = "咨询"
    priority: str = "normal"
    title: str
    content: str = ""


class TicketUpdateBody(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    resolution: Optional[str] = None


class AgentMessageBody(BaseModel):
    content: str


class ResolveTicketBody(BaseModel):
    resolution: str
    close: bool = False


class KbBody(BaseModel):
    title: str
    content: str
    category: str = "通用"
    tags: str = ""
    source: str = "人工录入"
    status: str = "published"


class KbSearchBody(BaseModel):
    query: str
    top_k: int = 5
    category: Optional[str] = None


class PartnerAsnBody(BaseModel):
    supplier_code: str
    warehouse_code: str
    expected_time: Optional[str] = None
    remark: str = ""
    items: list = []


# ---------- 工具函数 ----------
def _can_manage(user):
    perms = user.get("perms", [])
    return "*" in perms or "cs:ticket" in perms


def _parse_meta(row):
    for field in ("citations", "tool_results", "suggestions"):
        try:
            row[field] = json.loads(row.get(field) or ("[]" if field != "tool_results" else "[]"))
        except (ValueError, TypeError):
            row[field] = []
    return row


def _session_or_fail(user, sid):
    row = query_one("SELECT * FROM cs_session WHERE id=%s", (sid,))
    if not row:
        return None
    if row["user_id"] != user["id"] and not _can_manage(user):
        return None
    return row


def _agent_name(user):
    return user.get("real_name") or user.get("username") or "人工客服"


def _accept_ticket(ticket, user):
    """坐席接入：工单转处理中、会话转人工、写入系统提示"""
    session = query_one("SELECT * FROM cs_session WHERE id=%s", (ticket["session_id"],))
    if not session:
        return None
    name = _agent_name(user)
    execute("""UPDATE cs_ticket SET status='processing', assignee=%s WHERE id=%s""",
            (name, ticket["id"]))
    changed = session["status"] != "human" or (session.get("human_agent") or "") != name
    execute("""UPDATE cs_session SET status='human', human_agent=%s,
               handoff_at=COALESCE(handoff_at, NOW()), last_agent='HumanAgent' WHERE id=%s""",
            (name, session["id"]))
    if changed:
        execute_return_id("""INSERT INTO cs_message (session_id, role, content, agent, sender_name)
                             VALUES (%s,'system',%s,'HumanAgent',%s)""",
                          (session["id"], f"人工客服 {name} 已接入，你可以直接在这里沟通。", name))
        execute("UPDATE cs_session SET message_count=message_count+1 WHERE id=%s", (session["id"],))
    add_log(None, user, "智能客服", "接入会话", f"工单 {ticket['ticket_no']} 由 {name} 接入")
    return query_one("SELECT * FROM cs_session WHERE id=%s", (session["id"],))


def _partner_key():
    if os.getenv("WMS_PARTNER_KEY"):
        return os.getenv("WMS_PARTNER_KEY")
    row = query_one("SELECT config_value FROM sys_config WHERE config_key='partner_api_key'")
    return (row or {}).get("config_value") or PARTNER_API_KEY


def partner_auth(x_partner_key: str = Header(default="", alias="X-Partner-Key")):
    if x_partner_key != _partner_key():
        raise HTTPException(401, "合作方密钥无效，请检查请求头 X-Partner-Key")
    return True


def _parse_time(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value)[:19], fmt)
        except ValueError:
            continue
    return None


# ---------- 会话与问答 ----------
@router.get("/cs/agents")
def agent_catalog(user: dict = Depends(require_perm("cs:view"))):
    return ok({
        "agents": [
            {"name": "RouterAgent", "label": "意图路由", "icon": "🧭", "desc": "识别意图与商品/仓库/供应商/单据号实体，生成执行计划"},
            {"name": "KnowledgeAgent", "label": "RAG 知识检索", "icon": "📚", "desc": "BM25 + 哈希语义向量混合召回，返回带引用编号的知识片段"},
            {"name": "BusinessAgent", "label": "业务数据", "icon": "🗄️", "desc": "实时查询库存、单据、预警、补货、库容、客户等数据"},
            {"name": "SupplierAgent", "label": "供应商协同", "icon": "🚚", "desc": "供应商履约画像、默认供货商品、按供应商汇总补货清单"},
            {"name": "GeneralAgent", "label": "通用问答", "icon": "🌐", "desc": "日期时间、算术、寒暄与开放域问答，不依赖知识库"},
            {"name": "TicketAgent", "label": "工单升级", "icon": "🎫", "desc": "低置信度或用户要求人工时创建工单并跟踪 SLA"},
        ],
        "llm": {"enabled": llm.is_enabled(), "model": None if not llm.is_enabled() else "已配置"},
        "kb": retriever.kb_stats(),
    })


@router.get("/cs/suggestions")
def suggestions(user: dict = Depends(require_perm("cs:view"))):
    return ok({"items": [
        {"text": "蒙牛纯牛奶还有多少库存？", "icon": "📦", "intent": "库存查询"},
        {"text": "入库单 IN20260825001 进度到哪了？", "icon": "📥", "intent": "单据查询"},
        {"text": "供应商 SUP001 的到货准时率怎么样？", "icon": "🚚", "intent": "供应商协同"},
        {"text": "最近有哪些临期批次？", "icon": "⏰", "intent": "效期管理"},
        {"text": "按供应商汇总补货清单", "icon": "🧾", "intent": "供应商补货"},
        {"text": "入库单怎么创建和确认？", "icon": "📚", "intent": "业务知识"},
    ]})


@router.post("/cs/sessions")
def create_session(body: dict = None, user: dict = Depends(require_perm("cs:view"))):
    channel = (body or {}).get("channel", "web")
    title = (body or {}).get("title") or "新会话"
    row = orchestrator.create_session(user, channel, title)
    return ok(row, "会话已创建")


@router.get("/cs/sessions")
def list_sessions(page: int = 1, size: int = 10, keyword: str = "",
                  user: dict = Depends(require_perm("cs:view"))):
    where, params = "user_id=%s", [user["id"]]
    if keyword:
        where += " AND (title LIKE %s OR session_no LIKE %s)"
        params += [f"%{keyword}%"] * 2
    total = query_one(f"SELECT COUNT(*) c FROM cs_session WHERE {where}", params)["c"]
    rows = query(f"""SELECT * FROM cs_session WHERE {where}
                     ORDER BY update_time DESC LIMIT %s OFFSET %s""",
                 params + [size, (page - 1) * size])
    for r in rows:
        r["snippet"] = (query_one("""SELECT content FROM cs_message WHERE session_id=%s
                                     AND role='user' ORDER BY id DESC LIMIT 1""", (r["id"],)) or {}).get("content", "")
    return ok({"total": total, "list": rows})


@router.get("/cs/sessions/{sid}/messages")
def session_messages(sid: int, user: dict = Depends(require_perm("cs:view"))):
    s = _session_or_fail(user, sid)
    if not s:
        return fail("会话不存在或无权访问")
    rows = query("SELECT * FROM cs_message WHERE session_id=%s ORDER BY id", (sid,))
    return ok({"session": s, "messages": [_parse_meta(r) for r in rows]})


@router.get("/cs/sessions/{sid}/events")
def session_events(sid: int, after_id: int = 0, user: dict = Depends(require_perm("cs:view"))):
    """会话实时事件流：新消息（用户/坐席/AI/系统）与人工状态变化"""
    s = _session_or_fail(user, sid)
    if not s:
        return fail("会话不存在或无权访问")

    def gen():
        last = after_id
        status, agent = s["status"], s.get("human_agent") or ""
        yield "event: status\ndata: " + json.dumps(
            {"status": status, "human_agent": agent}, ensure_ascii=False) + "\n\n"
        end = time.time() + 60           # 单次连接 60s，前端自动续连
        ticks = 0
        while time.time() < end:
            rows = query("""SELECT id, session_id, role, content, agent, sender_name, create_time
                            FROM cs_message WHERE session_id=%s AND id>%s ORDER BY id LIMIT 30""",
                         (sid, last))
            for m in rows:
                last = m["id"]
                payload = json.dumps(m, ensure_ascii=False,
                                     default=lambda o: float(o) if isinstance(o, Decimal) else str(o))
                yield f"event: message\ndata: {payload}\n\n"
            cur = query_one("SELECT status, human_agent FROM cs_session WHERE id=%s", (sid,)) or {}
            if cur.get("status") != status or (cur.get("human_agent") or "") != agent:
                status, agent = cur.get("status"), cur.get("human_agent") or ""
                yield "event: status\ndata: " + json.dumps(
                    {"status": status, "human_agent": agent}, ensure_ascii=False) + "\n\n"
            time.sleep(1)
            ticks += 1
            if ticks % 15 == 0:
                yield ": ping\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.delete("/cs/sessions/{sid}")
def delete_session(sid: int, user: dict = Depends(require_perm("cs:view"))):
    s = _session_or_fail(user, sid)
    if not s:
        return fail("会话不存在或无权访问")
    execute("UPDATE cs_session SET status='archived' WHERE id=%s", (sid,))
    return ok(msg="会话已归档")


@router.post("/cs/chat")
def chat(body: ChatBody, user: dict = Depends(require_perm("cs:view"))):
    if not (body.message or "").strip():
        return fail("请输入问题")
    try:
        result = orchestrator.handle(user, body.session_id, body.message, body.channel)
        return ok(result)
    except ValueError as e:
        return fail(str(e))
    except Exception as e:
        print(f"[cs][chat] 处理失败: {e}")
        return fail("智能客服处理失败，请稍后重试或转人工客服")


@router.post("/cs/chat/stream")
def chat_stream(body: ChatBody, user: dict = Depends(require_perm("cs:view"))):
    """SSE 流式返回：先推送各 Agent 轨迹，再推送最终答案"""
    if not (body.message or "").strip():
        return fail("请输入问题")
    if body.session_id and not _session_or_fail(user, body.session_id):
        return fail("会话不存在或无权访问")

    def gen():
        try:
            for ev in orchestrator.stream(user, body.session_id, body.message, body.channel):
                payload = json.dumps(ev["data"], ensure_ascii=False,
                                     default=lambda o: float(o) if isinstance(o, Decimal) else str(o))
                yield f"event: {ev['event']}\ndata: {payload}\n\n"
        except Exception as e:
            print(f"[cs][stream] 处理失败: {e}")
            yield "event: error\ndata: " + json.dumps(
                {"msg": "智能客服处理失败，请稍后重试或转人工客服"}, ensure_ascii=False) + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/cs/messages/{mid}/feedback")
def feedback(mid: int, body: FeedbackBody, user: dict = Depends(require_perm("cs:view"))):
    msg = query_one("""SELECT m.*, s.user_id FROM cs_message m JOIN cs_session s ON m.session_id=s.id
                       WHERE m.id=%s""", (mid,))
    if not msg:
        return fail("消息不存在")
    if msg["user_id"] != user["id"] and not _can_manage(user):
        return fail("无权评价该消息")
    execute("UPDATE cs_message SET feedback=%s, feedback_comment=%s WHERE id=%s",
            (1 if body.rating > 0 else (-1 if body.rating < 0 else 0), body.comment[:500], mid))
    execute("""UPDATE cs_session SET satisfaction=
               COALESCE((SELECT AVG(feedback) FROM cs_message
                         WHERE session_id=%s AND feedback<>0), 0)
               WHERE id=%s""", (msg["session_id"], msg["session_id"]))
    return ok(msg="感谢反馈")


# ---------- 知识库 ----------
@router.get("/cs/kb")
def list_kb(page: int = 1, size: int = 10, keyword: str = "", category: str = "",
            status: str = "", user: dict = Depends(require_perm("cs:view"))):
    where, params = "1=1", []
    if keyword:
        where += " AND (title LIKE %s OR doc_no LIKE %s OR tags LIKE %s)"
        params += [f"%{keyword}%"] * 3
    if category:
        where += " AND category=%s"
        params.append(category)
    if status:
        where += " AND status=%s"
        params.append(status)
    total = query_one(f"SELECT COUNT(*) c FROM kb_document WHERE {where}", params)["c"]
    rows = query(f"""SELECT id, doc_no, title, category, tags, source, status, version, chunk_count,
                             update_by, create_time, update_time FROM kb_document WHERE {where}
                     ORDER BY id DESC LIMIT %s OFFSET %s""", params + [size, (page - 1) * size])
    cats = [r["category"] for r in query("SELECT DISTINCT category FROM kb_document WHERE category<>''")]
    return ok({"total": total, "list": rows, "categories": cats,
               "stats": retriever.kb_stats(), "builtin": len(KB_DOCS)})


@router.get("/cs/kb/{doc_id}")
def get_kb(doc_id: int, user: dict = Depends(require_perm("cs:view"))):
    row = query_one("SELECT * FROM kb_document WHERE id=%s", (doc_id,))
    if not row:
        return fail("文档不存在")
    row["chunks"] = query("""SELECT chunk_index, content, token_count FROM kb_chunk
                             WHERE doc_id=%s ORDER BY chunk_index""", (doc_id,))
    return ok(row)


@router.post("/cs/kb")
def create_kb(body: KbBody, user: dict = Depends(require_perm("cs:kb"))):
    if not body.title.strip() or not body.content.strip():
        return fail("标题与内容不能为空")
    doc_no = "KB-" + datetime.now().strftime("%Y%m%d%H%M%S")
    with transaction() as conn:
        doc_id = execute_return_id("""INSERT INTO kb_document
            (doc_no, title, category, tags, source, content, status, version, update_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,1,%s)""",
            (doc_no, body.title.strip(), body.category, body.tags, body.source,
             body.content, body.status, user["username"]), conn)
        if body.status == "published":
            retriever.ingest_document(doc_id, body.title, body.content, conn)
    add_log(None, user, "智能客服", "新增知识", f"{doc_no} {body.title}")
    return ok({"id": doc_id, "doc_no": doc_no}, "知识文档已创建")


@router.put("/cs/kb/{doc_id}")
def update_kb(doc_id: int, body: KbBody, user: dict = Depends(require_perm("cs:kb"))):
    row = query_one("SELECT * FROM kb_document WHERE id=%s", (doc_id,))
    if not row:
        return fail("文档不存在")
    with transaction() as conn:
        execute("""UPDATE kb_document SET title=%s, category=%s, tags=%s, source=%s, content=%s,
                   status=%s, version=version+1, update_by=%s WHERE id=%s""",
                (body.title, body.category, body.tags, body.source, body.content,
                 body.status, user["username"], doc_id), conn)
        if body.status == "published":
            retriever.ingest_document(doc_id, body.title, body.content, conn)
        else:
            execute("DELETE FROM kb_chunk WHERE doc_id=%s", (doc_id,), conn)
            execute("UPDATE kb_document SET chunk_count=0 WHERE id=%s", (doc_id,), conn)
            retriever.invalidate_cache()
    add_log(None, user, "智能客服", "更新知识", f"文档 {row['doc_no']}")
    return ok(msg="知识文档已更新")


@router.delete("/cs/kb/{doc_id}")
def delete_kb(doc_id: int, user: dict = Depends(require_perm("cs:kb"))):
    row = query_one("SELECT * FROM kb_document WHERE id=%s", (doc_id,))
    if not row:
        return fail("文档不存在")
    if row["doc_no"].startswith("KB-0") and row["source"] == "系统内置":
        return fail("系统内置文档不可删除，可改为草稿或编辑内容")
    with transaction() as conn:
        execute("DELETE FROM kb_chunk WHERE doc_id=%s", (doc_id,), conn)
        execute("DELETE FROM kb_document WHERE id=%s", (doc_id,), conn)
    retriever.invalidate_cache()
    add_log(None, user, "智能客服", "删除知识", f"文档 {row['doc_no']}")
    return ok(msg="已删除")


@router.post("/cs/kb/{doc_id}/reindex")
def reindex_kb(doc_id: int, user: dict = Depends(require_perm("cs:kb"))):
    row = query_one("SELECT * FROM kb_document WHERE id=%s", (doc_id,))
    if not row:
        return fail("文档不存在")
    count = retriever.ingest_document(doc_id, row["title"], row["content"])
    return ok({"chunks": count}, f"已重建 {count} 个知识切片")


@router.post("/cs/kb/reindex-all")
def reindex_all(user: dict = Depends(require_perm("cs:kb"))):
    data = retriever.rebuild_all()
    add_log(None, user, "智能客服", "重建索引", f"文档 {data['documents']} 篇 / 切片 {data['chunks']}")
    return ok(data, "知识库索引已重建")


@router.post("/cs/kb/seed-default")
def seed_default(user: dict = Depends(require_perm("cs:kb"))):
    added = seed_knowledge()
    return ok({"added": added}, f"已补充 {added} 篇内置知识")


@router.post("/cs/kb/search")
def kb_search(body: KbSearchBody, user: dict = Depends(require_perm("cs:view"))):
    hits = retriever.search_knowledge(body.query, top_k=body.top_k, category=body.category, min_score=0.05)
    return ok({"query": body.query, "hits": hits, "count": len(hits)})


# ---------- 工单 ----------
@router.post("/cs/tickets")
def create_ticket(body: TicketBody, user: dict = Depends(require_perm("cs:view"))):
    if not body.title.strip():
        return fail("请填写工单标题")
    session = _session_or_fail(user, body.session_id) if body.session_id else None
    if body.session_id and not session:
        return fail("会话不存在或无权访问")
    if body.priority not in ("high", "normal", "low"):
        body.priority = "normal"
    # 同一会话复用未关闭工单，避免重复排队
    if session:
        existing = query_one("""SELECT * FROM cs_ticket WHERE session_id=%s
                                AND status IN ('open','processing') ORDER BY id DESC LIMIT 1""",
                             (session["id"],))
        if existing:
            if session["status"] == "active":
                execute("""UPDATE cs_session SET status='waiting', handoff_at=NOW(),
                           last_agent='TicketAgent' WHERE id=%s""", (session["id"],))
            return ok({"id": existing["id"], "ticket_no": existing["ticket_no"], "reused": True},
                      "该会话已有进行中的工单，已转入人工队列")
    no = f"TK{datetime.now():%Y%m%d%H%M%S}{uuid.uuid4().hex[:3].upper()}"
    tid = execute_return_id("""INSERT INTO cs_ticket
        (ticket_no, session_id, user_id, username, category, priority, title, content, status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'open')""",
        (no, body.session_id, user["id"], user["username"], body.category,
         body.priority, body.title[:200], body.content))
    if session:
        execute("""UPDATE cs_session SET status='waiting', handoff_at=NOW(),
                   last_agent='TicketAgent' WHERE id=%s AND status='active'""", (session["id"],))
    add_log(None, user, "智能客服", "创建工单", f"工单 {no}，等待人工接入")
    return ok({"id": tid, "ticket_no": no, "status": "open"}, "工单已创建，正在等待人工接入")


@router.get("/cs/tickets")
def list_tickets(status: str = "", mine: int = 0, page: int = 1, size: int = 10,
                 user: dict = Depends(require_perm("cs:view"))):
    where, params = "1=1", []
    if status:
        where += " AND t.status=%s"
        params.append(status)
    if mine or not _can_manage(user):
        where += " AND t.user_id=%s"
        params.append(user["id"])
    total = query_one(f"SELECT COUNT(*) c FROM cs_ticket t WHERE {where}", params)["c"]
    rows = query(f"""SELECT t.*, s.session_no FROM cs_ticket t
                     LEFT JOIN cs_session s ON t.session_id=s.id
                     WHERE {where} ORDER BY FIELD(t.priority,'high','normal','low'), t.id DESC
                     LIMIT %s OFFSET %s""", params + [size, (page - 1) * size])
    counts = {r["status"]: r["c"] for r in query("SELECT status, COUNT(*) c FROM cs_ticket GROUP BY status")}
    return ok({"total": total, "list": rows, "counts": counts})


@router.get("/cs/human/queue")
def human_queue(user: dict = Depends(require_perm("cs:ticket"))):
    """人工工作台排队：待接入 / 处理中工单及最后一条消息"""
    rows = query("""SELECT t.*, s.session_no, s.status session_status, s.human_agent,
                           s.title session_title,
                           (SELECT m.content FROM cs_message m WHERE m.session_id=t.session_id
                            ORDER BY m.id DESC LIMIT 1) last_message,
                           (SELECT m.role FROM cs_message m WHERE m.session_id=t.session_id
                            ORDER BY m.id DESC LIMIT 1) last_role,
                           (SELECT m.sender_name FROM cs_message m WHERE m.session_id=t.session_id
                            ORDER BY m.id DESC LIMIT 1) last_sender,
                           (SELECT m.create_time FROM cs_message m WHERE m.session_id=t.session_id
                            ORDER BY m.id DESC LIMIT 1) last_time,
                           TIMESTAMPDIFF(MINUTE, t.create_time, NOW()) waiting_minutes,
                           COALESCE(TIMESTAMPDIFF(MINUTE, s.handoff_at, NOW()), 0) service_minutes
                    FROM cs_ticket t LEFT JOIN cs_session s ON t.session_id=s.id
                    WHERE t.status IN ('open','processing') AND t.session_id IS NOT NULL
                    ORDER BY FIELD(t.priority,'high','normal','low'), t.id""")
    counts = {r["status"]: r["c"] for r in query(
        "SELECT status, COUNT(*) c FROM cs_ticket WHERE status IN ('open','processing') GROUP BY status")}
    stats = {
        "today_resolved": query_one("""SELECT COUNT(*) c FROM cs_ticket
                                       WHERE status IN ('resolved','closed')
                                       AND DATE(update_time)=CURDATE()""")["c"],
        "avg_waiting": int(query_one("""SELECT COALESCE(AVG(TIMESTAMPDIFF(MINUTE, create_time, NOW())),0) c
                                        FROM cs_ticket WHERE status='open'""")["c"] or 0),
        "total_queue": sum(counts.values()),
    }
    return ok({"list": rows, "counts": counts, "stats": stats})


@router.post("/cs/tickets/{tid}/accept")
def accept_ticket(tid: int, user: dict = Depends(require_perm("cs:ticket"))):
    ticket = query_one("SELECT * FROM cs_ticket WHERE id=%s", (tid,))
    if not ticket:
        return fail("工单不存在")
    if ticket["status"] in ("resolved", "closed"):
        return fail("工单已结束，无法接入")
    if not ticket["session_id"]:
        return fail("该工单未关联在线会话，无法接入人工聊天")
    session = _accept_ticket(ticket, user)
    if not session:
        return fail("关联会话不存在")
    return ok({"session_id": session["id"], "session_no": session["session_no"],
               "human_agent": session["human_agent"], "ticket_no": ticket["ticket_no"],
               "ticket_status": "processing"}, "已接入人工会话")


@router.post("/cs/tickets/{tid}/resolve")
def resolve_ticket(tid: int, body: ResolveTicketBody, user: dict = Depends(require_perm("cs:ticket"))):
    ticket = query_one("SELECT * FROM cs_ticket WHERE id=%s", (tid,))
    if not ticket:
        return fail("工单不存在")
    if not (body.resolution or "").strip():
        return fail("请填写处理结论")
    if ticket["status"] in ("resolved", "closed"):
        return fail("工单已结束")
    name = _agent_name(user)
    status = "closed" if body.close else "resolved"
    execute("""UPDATE cs_ticket SET status=%s, resolution=%s,
               assignee=COALESCE(NULLIF(assignee,''), %s) WHERE id=%s""",
            (status, body.resolution.strip(), name, tid))
    session = query_one("SELECT * FROM cs_session WHERE id=%s", (ticket["session_id"],)) if ticket["session_id"] else None
    if session:
        execute("""UPDATE cs_session SET status='active', human_agent='', last_agent='HumanAgent'
                   WHERE id=%s""", (session["id"],))
        execute_return_id("""INSERT INTO cs_message (session_id, role, content, agent, sender_name)
                             VALUES (%s,'system',%s,'HumanAgent',%s)""",
                          (session["id"], "人工服务已结束，智能客服已恢复，你可以继续提问。", name))
        execute("UPDATE cs_session SET message_count=message_count+1 WHERE id=%s", (session["id"],))
    add_log(None, user, "智能客服", "结束人工服务",
            f"工单 {ticket['ticket_no']} 已{('关闭' if body.close else '解决')}：{body.resolution[:120]}")
    return ok({"ticket_no": ticket["ticket_no"], "status": status,
               "session_id": session["id"] if session else None}, "人工服务已结束")


@router.post("/cs/sessions/{sid}/agent-message")
def agent_message(sid: int, body: AgentMessageBody, user: dict = Depends(require_perm("cs:ticket"))):
    """人工坐席发送消息，实时推送给用户"""
    session = _session_or_fail(user, sid)
    if not session:
        return fail("会话不存在或无权访问")
    if not (body.content or "").strip():
        return fail("请输入消息内容")
    if session["status"] not in ("waiting", "human"):
        return fail("会话当前不在人工服务状态")
    name = _agent_name(user)
    if session["status"] == "waiting":
        ticket = query_one("""SELECT * FROM cs_ticket WHERE session_id=%s
                              AND status IN ('open','processing') ORDER BY id DESC LIMIT 1""", (sid,))
        if ticket:
            _accept_ticket(ticket, user)
        else:
            execute("""UPDATE cs_session SET status='human', human_agent=%s,
                       handoff_at=COALESCE(handoff_at,NOW()), last_agent='HumanAgent' WHERE id=%s""",
                    (name, sid))
    mid = execute_return_id("""INSERT INTO cs_message (session_id, role, content, agent, sender_name)
                               VALUES (%s,'agent',%s,'HumanAgent',%s)""",
                            (sid, body.content.strip(), name))
    execute("""UPDATE cs_session SET message_count=message_count+1, last_agent='HumanAgent',
               update_time=NOW() WHERE id=%s""", (sid,))
    add_log(None, user, "智能客服", "人工回复", f"会话 {session['session_no']}：{body.content[:120]}")
    return ok({"id": mid, "content": body.content.strip(), "sender_name": name,
               "role": "agent", "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
              "消息已发送")


@router.put("/cs/tickets/{tid}")
def update_ticket(tid: int, body: TicketUpdateBody, user: dict = Depends(require_perm("cs:ticket"))):
    row = query_one("SELECT * FROM cs_ticket WHERE id=%s", (tid,))
    if not row:
        return fail("工单不存在")
    fields, params = [], []
    for key in ("status", "priority", "assignee", "resolution"):
        val = getattr(body, key)
        if val is not None:
            fields.append(f"{key}=%s")
            params.append(val)
    if body.status == "resolved" and not (body.resolution or row.get("resolution")):
        return fail("解决工单前请填写处理结论")
    if not fields:
        return fail("没有需要更新的内容")
    if body.assignee is None and body.status == "processing" and not row.get("assignee"):
        fields.append("assignee=%s")
        params.append(user["username"])
    params.append(tid)
    execute(f"UPDATE cs_ticket SET {', '.join(fields)} WHERE id=%s", params)
    add_log(None, user, "智能客服", "处理工单", f"工单 {row['ticket_no']} → {body.status or '更新'}")
    return ok(msg="工单已更新")


# ---------- 统计 ----------
@router.get("/cs/stats")
def stats(user: dict = Depends(require_perm("cs:view"))):
    def c(sql, params=None):
        return query_one(sql, params)["c"]
    today = "DATE(create_time)=CURDATE()"
    data = {
        "sessions": c("SELECT COUNT(*) c FROM cs_session"),
        "messages": c("SELECT COUNT(*) c FROM cs_message"),
        "today_sessions": c(f"SELECT COUNT(*) c FROM cs_session WHERE {today}"),
        "avg_latency": round(float(query_one("""SELECT COALESCE(AVG(latency_ms),0) c FROM cs_message
                                                WHERE role='assistant' AND latency_ms>0""")["c"] or 0)),
        "good_feedback": c("SELECT COUNT(*) c FROM cs_message WHERE feedback=1"),
        "bad_feedback": c("SELECT COUNT(*) c FROM cs_message WHERE feedback=-1"),
        "open_tickets": c("SELECT COUNT(*) c FROM cs_ticket WHERE status IN ('open','processing')"),
        "resolved_tickets": c("SELECT COUNT(*) c FROM cs_ticket WHERE status IN ('resolved','closed')"),
        "kb": retriever.kb_stats(),
        "llm_enabled": llm.is_enabled(),
    }
    data["intents"] = query("""SELECT last_intent name, COUNT(*) value FROM cs_session
                               WHERE last_intent<>'' GROUP BY last_intent ORDER BY value DESC LIMIT 8""")
    data["agents"] = query("""SELECT agent name, COUNT(*) value, ROUND(AVG(latency_ms),0) avg_ms
                              FROM cs_agent_log WHERE create_time>=DATE_SUB(NOW(), INTERVAL 7 DAY)
                              GROUP BY agent ORDER BY value DESC""")
    data["recent_low"] = query("""SELECT m.id, m.confidence, m.content, m.create_time, s.id session_id
                                  FROM cs_message m JOIN cs_session s ON m.session_id=s.id
                                  WHERE m.role='assistant' AND m.confidence<0.5
                                  ORDER BY m.id DESC LIMIT 8""")
    data["trend"] = query("""SELECT DATE(create_time) d, COUNT(*) c FROM cs_message
                             WHERE role='user' AND create_time>=DATE_SUB(CURDATE(), INTERVAL 6 DAY)
                             GROUP BY DATE(create_time) ORDER BY d""")
    return ok(data)


# ---------- 供应商 / 商家开放接口 ----------
@router.get("/partner/supplier/{supplier_code}/scorecard")
def partner_scorecard(supplier_code: str, request: Request, _=Depends(partner_auth)):
    card = tools.supplier_scorecard(supplier_code)
    if not card:
        return fail("供应商不存在")
    card["data"]["api"] = {"partner": True, "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    return ok(card["data"], card["summary"])


@router.get("/partner/asns")
def partner_asns(supplier_code: str, status: str = "", limit: int = 20, _=Depends(partner_auth)):
    supplier = query_one("SELECT * FROM wms_supplier WHERE supplier_code=%s", (supplier_code,))
    if not supplier:
        return fail("供应商不存在")
    where, params = "a.supplier_id=%s", [supplier["id"]]
    if status:
        where += " AND a.status=%s"
        params.append(status)
    rows = query(f"""SELECT a.id, a.asn_no, a.status, a.expected_time, a.create_time,
                            w.warehouse_code, w.warehouse_name, a.remark
                     FROM wms_asn a JOIN wms_warehouse w ON a.warehouse_id=w.id
                     WHERE {where} ORDER BY a.id DESC LIMIT %s""", params + [min(limit, 100)])
    for r in rows:
        r["items"] = query("""SELECT p.sku, p.product_name, d.quantity FROM wms_asn_detail d
                              JOIN wms_product p ON d.product_id=p.id WHERE d.asn_id=%s""", (r["id"],))
    return ok({"supplier": {"code": supplier["supplier_code"], "name": supplier["supplier_name"]},
               "list": rows, "count": len(rows)})


@router.post("/partner/asns")
def partner_create_asn(body: PartnerAsnBody, request: Request, _=Depends(partner_auth)):
    """供应商 / 商家通过开放接口创建 ASN，直接进入现有收货流程"""
    if not body.items:
        return fail("请提供商品明细 items")
    supplier = query_one("SELECT * FROM wms_supplier WHERE supplier_code=%s", (body.supplier_code,))
    if not supplier:
        return fail("供应商编码不存在")
    warehouse = query_one("SELECT * FROM wms_warehouse WHERE warehouse_code=%s AND status=1", (body.warehouse_code,))
    if not warehouse:
        return fail("仓库编码不存在或已停用")
    items = []
    for it in body.items:
        product = query_one("SELECT * FROM wms_product WHERE sku=%s AND status=1", (str(it.get("sku", "")),))
        if not product:
            return fail(f"SKU 不存在：{it.get('sku')}")
        try:
            qty = int(it.get("quantity", 0))
        except (TypeError, ValueError):
            return fail(f"商品 {it.get('sku')} 数量格式错误")
        if qty <= 0:
            return fail(f"商品 {it.get('sku')} 数量必须大于 0")
        items.append({"product_id": product["id"], "quantity": qty})
    partner_user = {"id": None, "username": f"partner:{supplier['supplier_code']}",
                    "ip": request.client.host if request.client else ""}
    try:
        with transaction() as conn:
            asn_no = gen_no(conn, "ASN", "wms_asn", "asn_no")
            aid = execute_return_id("""INSERT INTO wms_asn
                (asn_no, warehouse_id, supplier_id, expected_time, status, remark, operator)
                VALUES (%s,%s,%s,%s,'pending',%s,%s)""",
                (asn_no, warehouse["id"], supplier["id"], _parse_time(body.expected_time),
                 (body.remark or "供应商开放接口创建")[:500], partner_user["username"]), conn)
            for it in items:
                execute("INSERT INTO wms_asn_detail (asn_id, product_id, quantity) VALUES (%s,%s,%s)",
                        (aid, it["product_id"], it["quantity"]), conn)
            add_log(conn, partner_user, "供应商接口", "创建ASN", f"{asn_no} 供应商 {supplier['supplier_code']}")
        return ok({"id": aid, "asn_no": asn_no, "status": "pending"}, "ASN 创建成功，等待仓库收货")
    except BizError as e:
        return fail(e.msg)
