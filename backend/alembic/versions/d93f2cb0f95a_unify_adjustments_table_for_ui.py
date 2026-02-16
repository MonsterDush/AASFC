from alembic import op
import sqlalchemy as sa

revision = "d93f2cb0f95a"
down_revision = "e3a1d9b7c2f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 1) adjustments table (NEW) ---
    op.create_table(
        "adjustments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id"), nullable=False, index=True),
        sa.Column("type", sa.String(length=20), nullable=False, index=True),  # penalty|writeoff|bonus
        sa.Column("member_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True, index=True),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_adjustments_venue_date", "adjustments", ["venue_id", "date"])
    op.create_index("ix_adjustments_venue_member_date", "adjustments", ["venue_id", "member_user_id", "date"])
    op.create_index("ix_adjustments_venue_type_date", "adjustments", ["venue_id", "type", "date"])

    # --- 2) OPTIONAL: backfill from old tables (если хочешь сохранить историю) ---
    # penalties -> adjustments(type='penalty')
    op.execute("""
        INSERT INTO adjustments (venue_id, type, member_user_id, date, amount, reason, is_active, created_by_user_id, created_at)
        SELECT venue_id, 'penalty', member_user_id, date, amount, reason, is_active, created_by_user_id, created_at
        FROM penalties
    """)
    # writeoffs -> adjustments(type='writeoff')
    op.execute("""
        INSERT INTO adjustments (venue_id, type, member_user_id, date, amount, reason, is_active, created_by_user_id, created_at)
        SELECT venue_id, 'writeoff', member_user_id, date, amount, reason, is_active, created_by_user_id, created_at
        FROM writeoffs
    """)
    # bonuses -> adjustments(type='bonus')
    op.execute("""
        INSERT INTO adjustments (venue_id, type, member_user_id, date, amount, reason, is_active, created_by_user_id, created_at)
        SELECT venue_id, 'bonus', member_user_id, date, amount, reason, is_active, created_by_user_id, created_at
        FROM bonuses
    """)

    # --- 3) adjustment_disputes конфликтует по структуре: переименуем старую и создадим новую ---
    # (если у тебя уже есть таблица adjustment_disputes из e3a1 — она другая)
    op.rename_table("adjustment_disputes", "adjustment_disputes_old")
    # comments тоже переименуем, чтобы не потерять
    op.rename_table("adjustment_dispute_comments", "adjustment_dispute_comments_old")

    op.create_table(
        "adjustment_disputes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("adjustment_id", sa.Integer(), sa.ForeignKey("adjustments.id"), nullable=False, index=True),
        sa.Column("message", sa.String(length=2000), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # --- 4) daily_report_attachments тоже конфликтует: старую сохраняем, создаём новую ---
    op.rename_table("daily_report_attachments", "daily_report_attachments_old")
    # daily_report_attachments: rename old indexes to avoid name collisions
    op.execute("ALTER INDEX IF EXISTS ix_daily_report_attachments_venue_id RENAME TO ix_daily_report_attachments_old_venue_id")
    op.execute("ALTER INDEX IF EXISTS ix_daily_report_attachments_report_id RENAME TO ix_daily_report_attachments_old_report_id")
    op.execute("ALTER INDEX IF EXISTS ix_report_att_report RENAME TO ix_report_att_report_old")


    op.create_table(
        "daily_report_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id"), nullable=False, index=True),
        sa.Column("report_date", sa.Date(), nullable=False, index=True),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    # drop new tables
    op.drop_table("daily_report_attachments")
    op.drop_table("adjustment_disputes")
    op.drop_index("ix_adjustments_venue_type_date", table_name="adjustments")
    op.drop_index("ix_adjustments_venue_member_date", table_name="adjustments")
    op.drop_index("ix_adjustments_venue_date", table_name="adjustments")
    op.drop_table("adjustments")

    # restore old names
    op.rename_table("daily_report_attachments_old", "daily_report_attachments")
    op.rename_table("adjustment_dispute_comments_old", "adjustment_dispute_comments")
    op.rename_table("adjustment_disputes_old", "adjustment_disputes")
