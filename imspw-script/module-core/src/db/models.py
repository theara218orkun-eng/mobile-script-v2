from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.dialects.postgresql import JSONB

Base = declarative_base()

class Task(Base):
    __tablename__ = "task_queue"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(255), nullable=False, index=True)
    task_type = Column(String(255), nullable=False)
    payload = Column(Text, nullable=False)
    status = Column(String(50), default="PENDING", index=True)
    
    created_at = Column(DateTime, server_default=func.now())
    processed_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<Task(id={self.id}, device_id='{self.device_id}', status='{self.status}')>"

class AgentAccount(Base):
    __tablename__ = "agent_account"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    role = Column(String(50), nullable=False)
    device_ip = Column(String(50), nullable=True)
    device_serial_id = Column(String(100), nullable=True)
    telegram = Column(JSONB, nullable=True)
    whatsapp = Column(JSONB, nullable=True)
    line = Column(JSONB, nullable=True)
    facebook = Column(JSONB, nullable=True)
    config = Column(JSONB, nullable=True)
    shift_hour = Column(JSONB, nullable=True)
    status = Column(String(20), default="offline", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

class ServiceSubscription(Base):
    __tablename__ = "service_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    private_groups = relationship("PrivateGroup", back_populates="service_subscription")

class PrivateGroup(Base):
    __tablename__ = "private_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    service_subscription_id = Column(Integer, ForeignKey("service_subscriptions.id"), nullable=False)
    invite_link = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    service_subscription = relationship("ServiceSubscription", back_populates="private_groups")
    user_subscriptions = relationship(
        "UserSubscription",
        secondary="user_subscription_private_groups",
        back_populates="private_groups"
    )

class UserSubscription(Base):
    __tablename__ = "user_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    uuid = Column(String(100), nullable=False)
    platform = Column(String(50), nullable=False)
    subscription_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    private_groups = relationship(
        "PrivateGroup",
        secondary="user_subscription_private_groups",
        back_populates="user_subscriptions"
    )

class UserSubscriptionPrivateGroup(Base):
    __tablename__ = "user_subscription_private_groups"

    user_subscription_id = Column(Integer, ForeignKey("user_subscriptions.id"), primary_key=True)
    private_group_id = Column(Integer, ForeignKey("private_groups.id"), primary_key=True)
