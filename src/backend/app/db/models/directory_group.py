import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.user import User

# Who is in which group, as the IdP's SCIM provisioning says.
group_members = Table(
    "directory_group_members",
    Base.metadata,
    Column(
        "group_id",
        ForeignKey(
            "directory_groups.id",
            name="directory_group_members_group_id_fkey",
            ondelete="CASCADE",
        ),
        primary_key=True,
    ),
    Column(
        "user_id",
        ForeignKey(
            "users.id", name="directory_group_members_user_id_fkey", ondelete="CASCADE"
        ),
        primary_key=True,
        index=True,
    ),
)


class DirectoryGroup(Base):
    """A group in the organization's IdP, such as sg-ai-compliance. The IdP
    keeps it in sync through SCIM; its name is what role rules match."""

    __tablename__ = "directory_groups"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "display_name", name="directory_groups_org_id_display_name_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", name="directory_groups_org_id_fkey"),
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(255))
    external_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    members: Mapped[list[User]] = relationship(secondary=group_members, lazy="selectin")
