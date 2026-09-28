"""Initial source-document and exact-locator schema."""

from alembic import op

from opencounsel.persistence.models import Base

revision = "0001_source_locator"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())

