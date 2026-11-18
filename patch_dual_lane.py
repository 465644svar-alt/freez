from pathlib import Path
import re

ROOT = Path("core")

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def write(path, text):
    (ROOT / path).write_text(text, encoding="utf-8")

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)

# ---------------------------------------------------------------------------
# context.rs: per-account interactive worker lifecycle state.
# ---------------------------------------------------------------------------
path = "src/context.rs"
text = read(path)

text = replace_once(
    text,
    "    /// Timestamp after which the SMTP loop checks for a keyupdate to send, or 0 if none is due.\n"
    "    pub(crate) next_keyupdate_check: AtomicI64,\n",
    "    /// Timestamp after which the SMTP loop checks for a keyupdate to send, or 0 if none is due.\n"
    "    pub(crate) next_keyupdate_check: AtomicI64,\n\n"
    "    /// Wakes the OurChat interactive SMTP lane. The worker owns its SMTP connection\n"
    "    /// and therefore reuses it across consecutive interactive messages.\n"
    "    pub(crate) ourchat_interactive_smtp_notify: Arc<Notify>,\n\n"
    "    /// Ensures there is at most one interactive SMTP worker per account context.\n"
    "    pub(crate) ourchat_interactive_smtp_worker_started: AtomicBool,\n",
    "context fields",
)

text = replace_once(
    text,
    "            next_keyupdate_check: AtomicI64::new(0),\n",
    "            next_keyupdate_check: AtomicI64::new(0),\n"
    "            ourchat_interactive_smtp_notify: Arc::new(Notify::new()),\n"
    "            ourchat_interactive_smtp_worker_started: AtomicBool::new(false),\n",
    "context init",
)
write(path, text)

# ---------------------------------------------------------------------------
# smtp.rs: explicit lane marker table + persistent interactive SMTP worker.
# ---------------------------------------------------------------------------
path = "src/smtp.rs"
text = read(path)

text = replace_once(
    text,
    "use std::collections::BTreeSet;\n",
    "use std::collections::BTreeSet;\n"
    "use std::sync::atomic::Ordering;\n",
    "smtp import",
)

anchor = """/// Tries to send all messages currently in `smtp`, `smtp_status_updates` and `smtp_mdns` tables.
pub(crate) async fn send_smtp_messages(context: &Context, connection: &mut Smtp) -> Result<()> {
"""
if anchor not in text:
    raise SystemExit("smtp send_smtp_messages anchor not found")

insert = r'''const OURCHAT_INTERACTIVE_LANE_TABLE: &str = "ourchat_smtp_lane_v1";

fn create_ourchat_interactive_lane_table(
    transaction: &mut rusqlite::Transaction<'_>,
) -> Result<()> {
    transaction.execute(
        "CREATE TABLE IF NOT EXISTS ourchat_smtp_lane_v1 (
            row_id INTEGER PRIMARY KEY NOT NULL,
            lane INTEGER NOT NULL DEFAULT 1
        ) STRICT",
        (),
    )?;
    Ok(())
}

/// Marks an smtp2 row as belonging to OurChat's interactive lane.
///
/// This table intentionally does not participate in Delta Chat's schema migration
/// versioning. Official Core versions simply ignore it, while OurChat can preserve
/// lane ownership across restarts without colliding with future upstream migrations.
pub(crate) fn mark_ourchat_interactive_smtp_row(
    transaction: &mut rusqlite::Transaction<'_>,
    row_id: i64,
) -> Result<()> {
    create_ourchat_interactive_lane_table(transaction)?;
    transaction.execute(
        "INSERT OR REPLACE INTO ourchat_smtp_lane_v1 (row_id, lane) VALUES (?, 1)",
        (row_id,),
    )?;
    Ok(())
}

async fn ensure_ourchat_interactive_lane_table(context: &Context) -> Result<()> {
    context
        .sql
        .execute(
            "CREATE TABLE IF NOT EXISTS ourchat_smtp_lane_v1 (
                row_id INTEGER PRIMARY KEY NOT NULL,
                lane INTEGER NOT NULL DEFAULT 1
            ) STRICT",
            (),
        )
        .await?;

    // smtp2 uses AUTOINCREMENT, so stale lane rows can never accidentally match a
    // future smtp job. Prune them anyway to keep the auxiliary table tiny.
    context
        .sql
        .execute(
            "DELETE FROM ourchat_smtp_lane_v1
             WHERE row_id NOT IN (SELECT id FROM smtp2)",
            (),
        )
        .await?;
    Ok(())
}

async fn send_ourchat_interactive_smtp_messages(
    context: &Context,
    connection: &mut Smtp,
) -> Result<bool> {
    ensure_ourchat_interactive_lane_table(context).await?;

    let rowids = context
        .sql
        .query_map_vec(
            "SELECT smtp2.id
             FROM smtp2
             INNER JOIN ourchat_smtp_lane_v1 AS lane
                     ON lane.row_id = smtp2.id
             WHERE lane.lane = 1
             ORDER BY smtp2.id ASC",
            (),
            |row| {
                let rowid: i64 = row.get(0)?;
                Ok(rowid)
            },
        )
        .await?;

    if rowids.is_empty() {
        return Ok(false);
    }

    info!(
        context,
        "OurChat interactive SMTP lane selected rows: {rowids:?}."
    );

    // Strict FIFO inside the interactive lane. A temporary failure stops the
    // pass so later text messages cannot overtake the failed one.
    for rowid in rowids {
        send_msg_to_smtp(context, connection, rowid)
            .await
            .context("Failed to send OurChat interactive message")?;
    }

    ensure_ourchat_interactive_lane_table(context).await?;
    Ok(true)
}

/// Starts (once per account) and wakes OurChat's persistent interactive SMTP worker.
///
/// The worker owns one Smtp instance, so the connection is reused between text messages.
/// It only selects rows explicitly marked for the interactive lane; the normal SMTP loop
/// is modified below to exclude those rows completely.
pub(crate) fn wake_ourchat_interactive_smtp_worker(context: &Context) {
    let notify = context.ourchat_interactive_smtp_notify.clone();

    if !context
        .ourchat_interactive_smtp_worker_started
        .swap(true, Ordering::AcqRel)
    {
        let weak = context.get_weak_context();
        let worker_notify = notify.clone();

        task::spawn(async move {
            let mut connection = Smtp::new();
            let mut retry_secs = 1_u64;

            loop {
                let ctx = match weak.upgrade() {
                    Ok(ctx) => ctx,
                    Err(_) => break,
                };

                match send_ourchat_interactive_smtp_messages(&ctx, &mut connection).await {
                    Ok(true) => {
                        retry_secs = 1;
                        // Drain anything that arrived while the previous row was sent.
                        continue;
                    }
                    Ok(false) => {
                        retry_secs = 1;
                        drop(ctx);
                        worker_worker_notify.notified().await;
                    }
                    Err(err) => {
                        warn!(
                            ctx,
                            "OurChat interactive SMTP worker failed: {:#}.",
                            err
                        );

                        let rate_wait = ctx.ratelimit.read().await.until_can_send();
                        let retry_wait = std::time::Duration::from_secs(retry_secs);
                        let wait = std::cmp::max(rate_wait, retry_wait);
                        retry_secs = retry_secs.saturating_mul(2).min(60);

                        drop(ctx);

                        // A newly queued interactive message is allowed to wake the worker
                        // earlier; FIFO is still preserved by the lane query itself.
                        tokio::select! {
                            _ = tokio::time::sleep(wait) => {},
                            _ = worker_notify.notified() => {},
                        }
                    }
                }
            }
        });
    }

    notify.notify_one();
}

'''

text = text.replace(anchor, insert + anchor, 1)

old_query = '''    let rowids = context
        .sql
        .query_map_vec("SELECT id FROM smtp2 ORDER BY id ASC", (), |row| {
            let rowid: i64 = row.get(0)?;
            Ok(rowid)
        })
        .await?;
'''
new_query = '''    ensure_ourchat_interactive_lane_table(context).await?;

    let rowids = context
        .sql
        .query_map_vec(
            "SELECT smtp2.id
             FROM smtp2
             LEFT JOIN ourchat_smtp_lane_v1 AS lane
                    ON lane.row_id = smtp2.id
             WHERE lane.row_id IS NULL
             ORDER BY smtp2.id ASC",
            (),
            |row| {
                let rowid: i64 = row.get(0)?;
                Ok(rowid)
            },
        )
        .await?;
'''
text = replace_once(text, old_query, new_query, "bulk smtp query")
write(path, text)

# ---------------------------------------------------------------------------
# chat.rs: atomically route interactive jobs before the bulk worker can see them.
# ---------------------------------------------------------------------------
path = "src/chat.rs"
text = read(path)

old_send = r'''pub async fn send_msg(context: &Context, chat_id: ChatId, msg: &mut Message) -> Result<MsgId> {
    ensure!(
        !chat_id.is_special(),
        "chat_id cannot be a special chat: {chat_id}"
    );

    if msg.state != MessageState::Undefined {
        msg.param.remove(Param::GuaranteeE2ee);
        msg.param.remove(Param::ForcePlaintext);
        // create_send_msg_jobs() will update `param` in the db.
    }

    // protect all system messages against RTLO attacks
    if msg.is_system_message() {
        msg.text = sanitize_bidi_characters(&msg.text);
    }

    if !prepare_send_msg(context, chat_id, msg).await?.is_empty() {
        if !msg.hidden {
            context.emit_msgs_changed(msg.chat_id, msg.id);
        }

        if msg.param.exists(Param::SetLatitude) {
            context.emit_location_changed(Some(ContactId::SELF)).await?;
        }

        context.scheduler.interrupt_smtp().await;
    }

    Ok(msg.id)
}
'''
new_send = r'''async fn send_msg_routed(
    context: &Context,
    chat_id: ChatId,
    msg: &mut Message,
    interactive: bool,
) -> Result<MsgId> {
    ensure!(
        !chat_id.is_special(),
        "chat_id cannot be a special chat: {chat_id}"
    );

    if msg.state != MessageState::Undefined {
        msg.param.remove(Param::GuaranteeE2ee);
        msg.param.remove(Param::ForcePlaintext);
        // create_send_msg_jobs() will update `param` in the db.
    }

    // protect all system messages against RTLO attacks
    if msg.is_system_message() {
        msg.text = sanitize_bidi_characters(&msg.text);
    }

    if !prepare_send_msg(context, chat_id, msg, interactive)
        .await?
        .is_empty()
    {
        if !msg.hidden {
            context.emit_msgs_changed(msg.chat_id, msg.id);
        }

        if msg.param.exists(Param::SetLatitude) {
            context.emit_location_changed(Some(ContactId::SELF)).await?;
        }

        if interactive {
            crate::smtp::wake_ourchat_interactive_smtp_worker(context);
        } else {
            context.scheduler.interrupt_smtp().await;
        }
    }

    Ok(msg.id)
}

pub async fn send_msg(context: &Context, chat_id: ChatId, msg: &mut Message) -> Result<MsgId> {
    send_msg_routed(context, chat_id, msg, false).await
}

/// Sends a message through OurChat's persistent interactive SMTP lane.
///
/// Interactive jobs are atomically marked in the same transaction that inserts them
/// into smtp2. The normal SMTP loop excludes those rows, so a large bulk SMTP DATA
/// transfer cannot capture them. A dedicated per-account worker preserves FIFO and
/// reuses its SMTP connection.
pub async fn send_msg_interactive(
    context: &Context,
    chat_id: ChatId,
    msg: &mut Message,
) -> Result<MsgId> {
    send_msg_routed(context, chat_id, msg, true).await
}
'''
text = replace_once(text, old_send, new_send, "send_msg routing")

text = replace_once(
    text,
    "    let rowids = prepare_send_msg(context, chat_id, msg).await?;\n",
    "    let rowids = prepare_send_msg(context, chat_id, msg, false).await?;\n",
    "send_msg_sync prepare",
)

text = replace_once(
    text,
    "async fn prepare_send_msg(\n    context: &Context,\n    chat_id: ChatId,\n    msg: &mut Message,\n) -> Result<Vec<i64>> {\n",
    "async fn prepare_send_msg(\n    context: &Context,\n    chat_id: ChatId,\n    msg: &mut Message,\n    interactive: bool,\n) -> Result<Vec<i64>> {\n",
    "prepare_send_msg signature",
)

text = replace_once(
    text,
    "    let row_ids = create_send_msg_jobs(context, msg)\n",
    "    let row_ids = create_send_msg_jobs(context, msg, interactive)\n",
    "prepare create jobs call",
)

text = replace_once(
    text,
    "async fn create_send_msg_jobs(context: &Context, msg: &mut Message) -> Result<Vec<i64>> {\n",
    "async fn create_send_msg_jobs(\n    context: &Context,\n    msg: &mut Message,\n    interactive: bool,\n) -> Result<Vec<i64>> {\n",
    "create_send_msg_jobs signature",
)

old_tx_start = '''        .transaction(|transaction| {
            // Sort the message to the bottom. Employ `msgs_index7` to compute `timestamp`.
'''
new_tx_start = '''        .transaction(|transaction| {
            if interactive {
                // Create the auxiliary lane table and mark rows inside this same
                // transaction, before either SMTP worker can observe the jobs.
                transaction.execute(
                    "CREATE TABLE IF NOT EXISTS ourchat_smtp_lane_v1 (
                        row_id INTEGER PRIMARY KEY NOT NULL,
                        lane INTEGER NOT NULL DEFAULT 1
                    ) STRICT",
                    (),
                )?;
            }

            // Sort the message to the bottom. Employ `msgs_index7` to compute `timestamp`.
'''
text = replace_once(text, old_tx_start, new_tx_start, "job transaction start")

old_pre = '''                let row_id = enqueue_mail(
                    transaction,
                    now,
                    msg.id,
                    &queued_pre_msg,
                    Some(&pre_side_effects),
                )
                .context("Failed to enqueue pre-message")?;
                row_ids.push(row_id)
'''
new_pre = '''                let row_id = enqueue_mail(
                    transaction,
                    now,
                    msg.id,
                    &queued_pre_msg,
                    Some(&pre_side_effects),
                )
                .context("Failed to enqueue pre-message")?;
                if interactive {
                    transaction.execute(
                        "INSERT OR REPLACE INTO ourchat_smtp_lane_v1 (row_id, lane)
                         VALUES (?, 1)",
                        (row_id,),
                    )?;
                }
                row_ids.push(row_id)
'''
text = replace_once(text, old_pre, new_pre, "pre row lane mark")

old_main = '''            row_ids.push(
                enqueue_mail(transaction, now, msg.id, &queued_msg, Some(&side_effects))
                    .context("Failed to enqueue message")?,
            );
            Ok(row_ids)
'''
new_main = '''            let row_id =
                enqueue_mail(transaction, now, msg.id, &queued_msg, Some(&side_effects))
                    .context("Failed to enqueue message")?;
            if interactive {
                transaction.execute(
                    "INSERT OR REPLACE INTO ourchat_smtp_lane_v1 (row_id, lane)
                     VALUES (?, 1)",
                    (row_id,),
                )?;
            }
            row_ids.push(row_id);
            Ok(row_ids)
'''
text = replace_once(text, old_main, new_main, "main row lane mark")
write(path, text)

# ---------------------------------------------------------------------------
# JSON-RPC: existing legacy plain-text method becomes the interactive entry point.
# Desktop 19.2.3.4 already calls this method only while a large transfer is active.
# ---------------------------------------------------------------------------
path = "deltachat-jsonrpc/src/api.rs"
text = read(path)

pattern = re.compile(
    r"(async fn misc_send_text_message\(.*?let mut msg = Message::new_text\(text\);\s*)"
    r"let message_id = deltachat::chat::send_msg\(&ctx, ChatId::new\(chat_id\), &mut msg\)\.await\?;",
    re.S,
)
replacement = (
    r"\1"
    "let message_id =\n"
    "            deltachat::chat::send_msg_interactive(&ctx, ChatId::new(chat_id), &mut msg).await?;"
)
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit(f"jsonrpc interactive entry: expected exactly 1 scoped match, found {count}")
write(path, text)

print("PATCH_OK: persistent dual-lane SMTP patch applied")
