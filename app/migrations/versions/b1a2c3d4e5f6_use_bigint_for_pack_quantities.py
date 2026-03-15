"""Use BIGINT for pack quantity fields

Revision ID: b1a2c3d4e5f6
Revises: fff59326eca4
Create Date: 2026-03-05 18:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b1a2c3d4e5f6"
down_revision: Union[str, None] = "fff59326eca4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Widen integer-like quantity fields to BIGINT to avoid overflow
    op.alter_column(
        "extracted_line_items",
        "detected_pack_quantity",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )

    op.alter_column(
        "lookup_audit_logs",
        "resolved_pack_quantity",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Revert BIGINT fields back to regular Integer
    op.alter_column(
        "extracted_line_items",
        "detected_pack_quantity",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )

    op.alter_column(
        "lookup_audit_logs",
        "resolved_pack_quantity",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )

