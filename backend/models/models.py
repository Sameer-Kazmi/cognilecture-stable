from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database import Base


class Lecture(Base):
    __tablename__ = "lectures"

    id = Column(Integer, primary_key=True, index=True)
    source_url = Column(String)
    title = Column(String)
    transcript = Column(Text)
    duration_sec = Column(Integer)
    status = Column(String, default="queued")   # queued | processing | completed | failed
    stage = Column(String, nullable=True)       # human-readable current step
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    notes = relationship("Note", back_populates="lecture", uselist=False)
    quizzes = relationship("Quiz", back_populates="lecture", uselist=False)


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, index=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"))
    content_markdown = Column(Text)
    diagrams = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lecture = relationship("Lecture", back_populates="notes")


class Quiz(Base):
    __tablename__ = "quizzes"

    id = Column(Integer, primary_key=True, index=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"))
    questions = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lecture = relationship("Lecture", back_populates="quizzes", uselist=False)


class ChatLog(Base):
    __tablename__ = "chat_logs"

    id = Column(Integer, primary_key=True, index=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"))
    role = Column(String)
    message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
