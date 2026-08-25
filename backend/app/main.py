from __future__ import annotations

import hashlib
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Generator

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl, field_validator
from sqlalchemy import CheckConstraint, DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./survey_exchange.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

class Base(DeclarativeBase): pass

class SurveyStatus(str, Enum): DRAFT="DRAFT"; ACTIVE="ACTIVE"; COMPLETED="COMPLETED"; CLOSED="CLOSED"; CANCELLED="CANCELLED"
class SessionStatus(str, Enum): STARTED="STARTED"; COMPLETED="COMPLETED"; EXPIRED="EXPIRED"
class TransactionType(str, Enum): RESERVATION="RESERVATION"; COMPLETION="COMPLETION"; REFUND="REFUND"; ADJUSTMENT="ADJUSTMENT"
class TransactionStatus(str, Enum): LOCKED="LOCKED"; PENDING="PENDING"; CONFIRMED="CONFIRMED"; RETURNED="RETURNED"

class Profile(Base):
    __tablename__="profiles"
    id: Mapped[str] = mapped_column(String(64), primary_key=True) # Supabase auth.users UUID in production
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    roll_number: Mapped[str] = mapped_column(String(32), unique=True)
    gender: Mapped[str] = mapped_column(String(24))
    program: Mapped[str] = mapped_column(String(32))
    batch: Mapped[int] = mapped_column(Integer)
    department: Mapped[str] = mapped_column(String(64), index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(16), default="STUDENT")
    credits: Mapped[int] = mapped_column(Integer, default=0)
    locked_credits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Survey(Base):
    __tablename__="surveys"
    id: Mapped[int] = mapped_column(primary_key=True)
    creator_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    google_form_url: Mapped[str] = mapped_column(Text)
    form_id: Mapped[str] = mapped_column(String(128))
    participation_field_entry: Mapped[str] = mapped_column(String(128))
    webhook_secret_hash: Mapped[str] = mapped_column(String(64))
    estimated_minutes: Mapped[int] = mapped_column(Integer)
    reward_per_response: Mapped[int] = mapped_column(Integer)
    status: Mapped[SurveyStatus] = mapped_column(SAEnum(SurveyStatus), default=SurveyStatus.DRAFT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    requirements: Mapped[list["SurveyRequirement"]] = relationship(cascade="all, delete-orphan")
    __table_args__=(CheckConstraint("reward_per_response between 1 and 10"), CheckConstraint("estimated_minutes > 0"))

class SurveyRequirement(Base):
    __tablename__="survey_requirements"
    id: Mapped[int] = mapped_column(primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id", ondelete="CASCADE"), index=True)
    department: Mapped[str] = mapped_column(String(64))
    year: Mapped[int] = mapped_column(Integer)
    gender: Mapped[str] = mapped_column(String(24))
    quota: Mapped[int] = mapped_column(Integer)
    filled: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__=(UniqueConstraint("survey_id","department","year","gender"), CheckConstraint("quota > 0"), CheckConstraint("filled >= 0 and filled <= quota"))

class SurveySession(Base):
    __tablename__="survey_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("survey_requirements.id"))
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[SessionStatus] = mapped_column(SAEnum(SessionStatus), default=SessionStatus.STARTED)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__=(UniqueConstraint("survey_id","user_id"),)

class Response(Base):
    __tablename__="responses"
    id: Mapped[int] = mapped_column(primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"))
    session_id: Mapped[int] = mapped_column(ForeignKey("survey_sessions.id"), unique=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__=(UniqueConstraint("survey_id","user_id"),)

class CreditTransaction(Base):
    __tablename__="credit_transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    survey_id: Mapped[int | None] = mapped_column(ForeignKey("surveys.id"), nullable=True)
    amount: Mapped[int] = mapped_column(Integer)
    type: Mapped[TransactionType] = mapped_column(SAEnum(TransactionType))
    status: Mapped[TransactionStatus] = mapped_column(SAEnum(TransactionStatus))
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ProfileIn(BaseModel):
    roll_number: str = Field(min_length=3, max_length=32)
    gender: str
    program: str
    batch: int = Field(ge=2000, le=2100)
    department: str
    year: int = Field(ge=1, le=8)

class RequirementIn(BaseModel):
    department: str
    year: int = Field(ge=1, le=8)
    gender: str
    quota: int = Field(ge=1, le=1000)

class SurveyIn(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10, max_length=5000)
    google_form_url: HttpUrl
    form_id: str = Field(min_length=3, max_length=128)
    participation_field_entry: str = Field(min_length=3, max_length=128, description="Google Forms entry.<id> field key")
    estimated_minutes: int = Field(ge=1, le=180)
    reward_per_response: int = Field(ge=1, le=10)
    requirements: list[RequirementIn] = Field(min_length=1)
    @field_validator("requirements")
    @classmethod
    def mutually_exclusive(cls, values):
        keys=[(x.department.lower(),x.year,x.gender.lower()) for x in values]
        if len(keys)!=len(set(keys)): raise ValueError("Each demographic quota must be unique")
        return values

class WebhookIn(BaseModel):
    survey_id: int
    participation_token: str
    submitted_at: datetime | None = None
    form_id: str
    webhook_secret: str

class CreditAdjustmentIn(BaseModel):
    amount: int = Field(ge=-1000, le=1000)
    reason: str = Field(min_length=3, max_length=240)

def get_db() -> Generator[Session, None, None]:
    db=SessionLocal()
    try: yield db
    finally: db.close()

def current_user(authorization: str | None = Header(default=None), x_demo_user: str | None = Header(default=None), x_demo_email: str | None = Header(default=None), db: Session = Depends(get_db)) -> Profile:
    demo_mode=os.getenv("DEV_MODE", "true").lower()=="true"
    if demo_mode and x_demo_user:
        identity={"id":x_demo_user,"email":x_demo_email}
    else:
        if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401,"Missing Supabase access token")
        url,key=os.getenv("SUPABASE_URL"),os.getenv("SUPABASE_ANON_KEY")
        if not url or not key: raise HTTPException(500,"Supabase auth is not configured")
        response=httpx.get(f"{url.rstrip('/')}/auth/v1/user",headers={"apikey":key,"Authorization":authorization},timeout=5)
        if response.status_code != 200: raise HTTPException(401,"Invalid or expired Supabase access token")
        identity=response.json()
    email=(identity.get("email") or "").lower()
    if not email.endswith("@nitc.ac.in"): raise HTTPException(403,"NITC email required")
    admins={x.strip().lower() for x in os.getenv("ADMIN_EMAILS","").split(",") if x.strip()}
    user=db.get(Profile,identity["id"])
    if not user:
        user=Profile(id=identity["id"],email=email,roll_number="pending-"+identity["id"],gender="Unspecified",program="Unspecified",batch=2024,department="Unspecified",year=1,role="ADMIN" if email in admins else "STUDENT")
        db.add(user); db.commit(); db.refresh(user)
    return user

def require_profile(user: Profile) -> None:
    if user.department == "Unspecified": raise HTTPException(409, "Complete your profile first")

def require_admin(user: Profile) -> None:
    if user.role != "ADMIN": raise HTTPException(403, "Administrator access required")

def secret_hash(value: str) -> str: return hashlib.sha256(value.encode()).hexdigest()
def prefilled_url(survey: Survey, token: str) -> str:
    sep="&" if "?" in survey.google_form_url else "?"
    return f"{survey.google_form_url}{sep}{survey.participation_field_entry}={token}"

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine) # local/dev convenience; production uses supplied SQL migration
    yield
app=FastAPI(title="NITC Survey Exchange API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "").split(",") if os.getenv("CORS_ORIGINS") else [],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root(): return {"name":"NITC Survey Exchange API","status":"running","docs":"/docs","health":"/health"}

@app.get("/health")
def health(): return {"status":"ok"}

@app.put("/me", status_code=200)
def update_profile(payload: ProfileIn, user: Profile=Depends(current_user), db: Session=Depends(get_db)):
    for k,v in payload.model_dump().items(): setattr(user,k,v)
    db.commit(); return {"id":user.id,"credits":user.credits}

@app.get("/me")
def me(user: Profile=Depends(current_user)):
    return {"id":user.id,"email":user.email,"role":user.role,"roll_number":user.roll_number,"department":user.department,"year":user.year,"gender":user.gender,"available_credits":user.credits,"locked_credits":user.locked_credits}

@app.post("/surveys", status_code=201)
def create_survey(payload: SurveyIn, user: Profile=Depends(current_user), db: Session=Depends(get_db)):
    require_profile(user)
    total=sum(r.quota for r in payload.requirements); cost=total*payload.reward_per_response
    if user.credits < cost: raise HTTPException(409, f"Need {cost} credits; available {user.credits}")
    raw_secret=secrets.token_urlsafe(32)
    try:
        user.credits-=cost; user.locked_credits+=cost
        values=payload.model_dump(exclude={"requirements"}); values["google_form_url"]=str(payload.google_form_url)
        survey=Survey(creator_id=user.id, **values, webhook_secret_hash=secret_hash(raw_secret), status=SurveyStatus.ACTIVE)
        db.add(survey); db.flush()
        db.add_all([SurveyRequirement(survey_id=survey.id, **r.model_dump()) for r in payload.requirements])
        db.add(CreditTransaction(user_id=user.id,survey_id=survey.id,amount=-cost,type=TransactionType.RESERVATION,status=TransactionStatus.LOCKED,idempotency_key=f"reservation:{survey.id}"))
        db.commit()
    except Exception:
        db.rollback(); raise
    return {"id":survey.id,"status":survey.status,"locked_credits":cost,"webhook_secret":raw_secret,"warning":"Copy the secret now; it is never returned again."}

@app.get("/surveys/feed")
def feed(user: Profile=Depends(current_user), db: Session=Depends(get_db)):
    require_profile(user)
    rows=db.execute(select(Survey,SurveyRequirement).join(SurveyRequirement).where(Survey.status==SurveyStatus.ACTIVE,SurveyRequirement.department==user.department,SurveyRequirement.year==user.year,SurveyRequirement.gender==user.gender,SurveyRequirement.filled < SurveyRequirement.quota)).all()
    return [{"id":s.id,"title":s.title,"description":s.description,"estimated_minutes":s.estimated_minutes,"reward":s.reward_per_response,"remaining":r.quota-r.filled} for s,r in rows]

@app.post("/surveys/{survey_id}/participate", status_code=201)
def participate(survey_id: int, user: Profile=Depends(current_user), db: Session=Depends(get_db)):
    require_profile(user)
    survey=db.get(Survey,survey_id)
    if not survey or survey.status != SurveyStatus.ACTIVE: raise HTTPException(404,"Active survey not found")
    requirement=db.scalar(select(SurveyRequirement).where(SurveyRequirement.survey_id==survey_id,SurveyRequirement.department==user.department,SurveyRequirement.year==user.year,SurveyRequirement.gender==user.gender,SurveyRequirement.filled < SurveyRequirement.quota).with_for_update())
    if not requirement: raise HTTPException(409,"No quota available for your group")
    existing=db.scalar(select(SurveySession).where(SurveySession.survey_id==survey_id,SurveySession.user_id==user.id))
    if existing: return {"token":existing.token,"url":prefilled_url(survey,existing.token),"status":existing.status}
    token=secrets.token_urlsafe(18)
    session=SurveySession(survey_id=survey_id,user_id=user.id,requirement_id=requirement.id,token=token)
    db.add(session); db.commit()
    return {"token":token,"url":prefilled_url(survey,token),"status":"STARTED"}

@app.post("/webhooks/google-form")
def google_webhook(payload: WebhookIn, db: Session=Depends(get_db)):
    survey=db.get(Survey,payload.survey_id)
    if not survey or survey.form_id != payload.form_id or not secrets.compare_digest(survey.webhook_secret_hash,secret_hash(payload.webhook_secret)): raise HTTPException(401,"Invalid webhook credentials")
    session=db.scalar(select(SurveySession).where(SurveySession.token==payload.participation_token).with_for_update())
    if not session or session.survey_id != survey.id: raise HTTPException(404,"Invalid participation token")
    if session.status == SessionStatus.COMPLETED: return {"accepted":True,"idempotent":True}
    requirement=db.get(SurveyRequirement,session.requirement_id); respondent=db.get(Profile,session.user_id); creator=db.get(Profile,survey.creator_id)
    if not requirement or requirement.filled >= requirement.quota or survey.status != SurveyStatus.ACTIVE: raise HTTPException(409,"Survey quota is closed")
    try:
        db.add(Response(survey_id=survey.id,user_id=session.user_id,session_id=session.id))
        session.status=SessionStatus.COMPLETED; requirement.filled+=1
        creator.locked_credits-=survey.reward_per_response
        respondent.credits+=survey.reward_per_response
        db.add(CreditTransaction(user_id=respondent.id,survey_id=survey.id,amount=survey.reward_per_response,type=TransactionType.COMPLETION,status=TransactionStatus.CONFIRMED,idempotency_key=f"completion:{session.id}"))
        if all(r.filled >= r.quota for r in survey.requirements): survey.status=SurveyStatus.COMPLETED
        db.commit()
    except Exception:
        db.rollback(); raise
    return {"accepted":True,"idempotent":False,"survey_status":survey.status}

@app.get("/surveys/{survey_id}/dashboard")
def survey_dashboard(survey_id: int, user: Profile=Depends(current_user), db: Session=Depends(get_db)):
    survey=db.get(Survey,survey_id)
    if not survey or survey.creator_id != user.id: raise HTTPException(404,"Survey not found")
    return {"id":survey.id,"title":survey.title,"status":survey.status,"requirements":[{"department":r.department,"year":r.year,"gender":r.gender,"filled":r.filled,"quota":r.quota} for r in survey.requirements]}

@app.get("/admin/overview")
def admin_overview(user: Profile=Depends(current_user), db: Session=Depends(get_db)):
    require_admin(user)
    return {"users":db.scalar(select(func.count()).select_from(Profile)),"active_surveys":db.scalar(select(func.count()).select_from(Survey).where(Survey.status==SurveyStatus.ACTIVE)),"responses":db.scalar(select(func.count()).select_from(Response)),"locked_credits":db.scalar(select(func.coalesce(func.sum(Profile.locked_credits),0)))}

@app.post("/admin/users/{user_id}/credits")
def adjust_credits(user_id: str, payload: CreditAdjustmentIn, user: Profile=Depends(current_user), db: Session=Depends(get_db)):
    require_admin(user)
    target=db.get(Profile,user_id)
    if not target: raise HTTPException(404,"User not found")
    if target.credits + payload.amount < 0: raise HTTPException(409,"Adjustment would make credits negative")
    target.credits += payload.amount
    db.add(CreditTransaction(user_id=target.id,survey_id=None,amount=payload.amount,type=TransactionType.ADJUSTMENT,status=TransactionStatus.CONFIRMED,idempotency_key=f"admin:{user.id}:{target.id}:{secrets.token_urlsafe(12)}"))
    db.commit(); return {"user_id":target.id,"available_credits":target.credits,"reason":payload.reason}
