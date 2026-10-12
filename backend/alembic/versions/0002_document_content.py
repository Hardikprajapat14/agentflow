"""store uploaded file bytes in the database (works on ephemeral-disk hosts)"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("content", sa.LargeBinary, nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "content")
