"""Accounts are global; each User remains a workspace-scoped membership."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base
from .models import utcnow


class Account(Base):
    __tablename__ = 'accounts'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(250), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AccountMembership(Base):
    __tablename__ = 'account_memberships'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey('accounts.id'), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    __table_args__ = (UniqueConstraint('account_id', 'workspace_id'),)


class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey('accounts.id'), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Invitation(Base):
    __tablename__ = 'invitations'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    team_id: Mapped[str] = mapped_column(ForeignKey('teams.id'))
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    email: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InvitationDelivery(Base):
    __tablename__ = 'invitation_deliveries'
    invitation_id: Mapped[str] = mapped_column(ForeignKey('invitations.token_hash', ondelete='CASCADE'), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthRateLimit(Base):
    __tablename__ = 'auth_rate_limits'
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class ResourceLease(Base):
    __tablename__ = 'resource_leases'
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    resource: Mapped[str] = mapped_column(String(24), index=True)
    workspace_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AccountMFA(Base):
    __tablename__ = 'account_mfa'
    account_id: Mapped[str] = mapped_column(ForeignKey('accounts.id'), primary_key=True)
    secret_encrypted: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_counter: Mapped[int] = mapped_column(Integer, default=-1)
    recovery_hashes: Mapped[str] = mapped_column(Text, default='[]')
    setup_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AccountEmailVerification(Base):
    __tablename__ = 'account_email_verification'
    account_id: Mapped[str] = mapped_column(ForeignKey('accounts.id'), primary_key=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AccountToken(Base):
    __tablename__ = 'account_tokens'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey('accounts.id'), index=True)
    purpose: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class OperationalSignal(Base):
    """Aggregate service health without request content or user identifiers."""
    __tablename__ = 'operational_signals'
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
