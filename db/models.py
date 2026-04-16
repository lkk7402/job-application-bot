"""SQLAlchemy ORM models for the job application tracker."""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Date,
    ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    external_id = Column(String(256), nullable=False)
    source = Column(String(32), nullable=False)        # 'linkedin' | 'seek'
    title = Column(String(256), nullable=False)
    company = Column(String(256), nullable=False)
    location = Column(String(256))
    url = Column(Text, nullable=False)
    description = Column(Text)
    salary_text = Column(String(256))
    job_type = Column(String(64))
    posted_date = Column(String(64))
    scraped_at = Column(DateTime, default=datetime.utcnow)

    # AI scoring
    match_score = Column(Integer)
    match_strengths = Column(Text)       # JSON array string
    match_gaps = Column(Text)            # JSON array string
    match_recommendation = Column(Text)
    is_filtered_out = Column(Boolean, default=False)

    applications = relationship("Application", back_populates="job")
    tailored_docs = relationship("TailoredDocument", back_populates="job")
    portfolio_projects = relationship("PortfolioProject", back_populates="job")

    __table_args__ = (UniqueConstraint("external_id", "source"),)


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)

    # Status state machine:
    # pending → tailoring → awaiting_confirmation → applying → applied / failed / skipped
    # applied → interviewing → offer / rejected / withdrawn
    status = Column(String(32), nullable=False, default="pending")

    applied_at = Column(DateTime)
    confirmation_text = Column(Text)
    resume_doc_id = Column(Integer, ForeignKey("tailored_documents.id"))
    cover_letter_doc_id = Column(Integer, ForeignKey("tailored_documents.id"))
    project_id = Column(Integer, ForeignKey("portfolio_projects.id"))
    notes = Column(Text)
    follow_up_date = Column(Date)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = relationship("Job", back_populates="applications")
    resume_doc = relationship("TailoredDocument", foreign_keys=[resume_doc_id])
    cover_letter_doc = relationship("TailoredDocument", foreign_keys=[cover_letter_doc_id])
    project = relationship("PortfolioProject", foreign_keys=[project_id])


class TailoredDocument(Base):
    __tablename__ = "tailored_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    doc_type = Column(String(32), nullable=False)   # 'resume' | 'cover_letter'
    content_md = Column(Text)
    file_path = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("Job", back_populates="tailored_docs")


class PortfolioProject(Base):
    __tablename__ = "portfolio_projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id"))
    repo_name = Column(String(256), nullable=False)
    repo_url = Column(Text)
    title = Column(String(256))
    description = Column(Text)
    tech_stack = Column(Text)       # JSON array string
    generated_at = Column(DateTime, default=datetime.utcnow)
    pushed_at = Column(DateTime)

    job = relationship("Job", back_populates="portfolio_projects")


class SearchRun(Base):
    __tablename__ = "search_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)
    jobs_found = Column(Integer, default=0)
    jobs_new = Column(Integer, default=0)
    sources_used = Column(Text)     # JSON array string
    error = Column(Text)


class DigestLog(Base):
    __tablename__ = "digest_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sent_at = Column(DateTime, default=datetime.utcnow)
    applications_count = Column(Integer)
    new_jobs_count = Column(Integer)
    email_preview = Column(Text)
