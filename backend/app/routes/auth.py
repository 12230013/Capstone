import hashlib
import os
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from pymongo.errors import DuplicateKeyError
from app.database.connection import sessions_collection, activity_collection

from app.schemas.user import UserCreate, UserLogin
from app.database.connection import (
    users_collection,
    password_reset_collection,
)
from app.utils.security import hash_password, verify_password
from app.utils.sessions import create_session, require_session, public_user, check_origin, COOKIE_NAME


router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"],
)


# --------------------------------------------------
# REQUEST SCHEMAS
# --------------------------------------------------

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str = Field(pattern=r"^[0-9]{6}$")


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    reset_token: str = Field(min_length=32, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, value):
        return UserCreate.validate_password(value)


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def hash_value(value: str) -> str:
    """Hash an OTP or reset token before storing it."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def send_otp_email(email: str, otp: str):
    """Send a password-reset OTP using Gmail SMTP."""

    sender = os.getenv("SMTP_EMAIL")
    app_password = os.getenv("SMTP_APP_PASSWORD")

    if not sender or not app_password:
        raise RuntimeError("SMTP email configuration is missing.")

    message = EmailMessage()
    message["Subject"] = "ACC Password Reset OTP"
    message["From"] = sender
    message["To"] = email

    message.set_content(
        f"""Hello,

Your ACC password-reset OTP is: {otp}

This OTP expires in 10 minutes.
Do not share this code with anyone.

If you did not request a password reset,
you can ignore this email.

Anti-Corruption Commission"""
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as smtp:
        smtp.login(sender, app_password)
        smtp.send_message(message)


@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordRequest, request: Request):
    check_origin(request)
    if users_collection is None or password_reset_collection is None:
        raise HTTPException(status_code=503, detail="Database connection is not available.")
    if not os.getenv("SMTP_EMAIL") or not os.getenv("SMTP_APP_PASSWORD"):
        raise HTTPException(status_code=503, detail="Password reset email is not configured.")

    email = str(data.email).strip().lower()
    result = {"message": "If the email is registered, a verification code will be sent."}
    user = users_collection.find_one({"email": email}, {"_id": 1})
    if user is None:
        return result

    now = datetime.now(timezone.utc)
    otp = f"{secrets.randbelow(1_000_000):06d}"
    challenge = secrets.token_hex(16)
    try:
        password_reset_collection.replace_one(
            {"_id": email, "next_request_at": {"$lte": now}},
            {
                "_id": email,
                "user_id": user["_id"],
                "challenge": challenge,
                "otp_hash": hash_value(challenge + otp),
                "attempts_remaining": 5,
                "expires_at": now + timedelta(minutes=10),
                "next_request_at": now + timedelta(minutes=1),
            },
            upsert=True,
        )
    except DuplicateKeyError:
        return result

    try:
        send_otp_email(email, otp)
    except (OSError, smtplib.SMTPException):
        password_reset_collection.delete_one({"_id": email, "challenge": challenge})
        raise HTTPException(status_code=503, detail="Unable to send a verification email. Please try again later.")
    return result


@router.post("/verify-otp")
def verify_otp(data: VerifyOTPRequest, request: Request):
    check_origin(request)
    if password_reset_collection is None:
        raise HTTPException(status_code=503, detail="Database connection is not available.")

    email = str(data.email).strip().lower()
    now = datetime.now(timezone.utc)
    active = {
        "_id": email,
        "expires_at": {"$gt": now},
        "attempts_remaining": {"$gt": 0},
    }
    record = password_reset_collection.find_one_and_update(
        active, {"$inc": {"attempts_remaining": -1}}
    )
    if record and secrets.compare_digest(record["otp_hash"], hash_value(record["challenge"] + data.otp)):
        token = secrets.token_urlsafe(32)
        updated = password_reset_collection.update_one(
            {"_id": email, "challenge": record["challenge"], "otp_hash": record["otp_hash"]},
            {
                "$set": {"reset_token_hash": hash_value(token), "reset_expires_at": now + timedelta(minutes=10)},
                "$unset": {"otp_hash": "", "attempts_remaining": ""},
            },
        )
        if updated.modified_count:
            return {"reset_token": token}
    raise HTTPException(status_code=400, detail="The verification code is invalid or expired.")


@router.post("/reset-password")
def reset_password(data: ResetPasswordRequest, request: Request):
    check_origin(request)
    if any(collection is None for collection in (users_collection, password_reset_collection, sessions_collection)):
        raise HTTPException(status_code=503, detail="Database connection is not available.")

    email = str(data.email).strip().lower()
    now = datetime.now(timezone.utc)
    token_filter = {
        "_id": email,
        "reset_token_hash": hash_value(data.reset_token),
        "reset_expires_at": {"$gt": now},
    }
    if password_reset_collection.find_one(token_filter, {"_id": 1}) is None:
        raise HTTPException(status_code=400, detail="The reset link is invalid or expired. Request a new code.")
    new_password = hash_password(data.new_password)
    record = password_reset_collection.find_one_and_delete(token_filter)
    if record is None:
        raise HTTPException(status_code=400, detail="The reset link is invalid or expired. Request a new code.")
    updated = users_collection.update_one(
        {"_id": record["user_id"], "email": email}, {"$set": {"password": new_password}}
    )
    if not updated.matched_count:
        raise HTTPException(status_code=400, detail="The reset link is invalid or expired. Request a new code.")
    sessions_collection.update_many(
        {"user_id": str(record["user_id"]), "ended_at": None}, {"$set": {"ended_at": now}}
    )
    return {"message": "Password reset successfully."}


# --------------------------------------------------
# SIGNUP
# --------------------------------------------------

@router.post("/signup")
def signup(user: UserCreate, request: Request):
    check_origin(request)
    if users_collection is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection is not available."
        )

    existing_employee = users_collection.find_one({
        "employee_id": user.employee_id
    })

    if existing_employee:
        raise HTTPException(
            status_code=400,
            detail="Employee ID is already registered",
        )

    email = str(user.email).lower().strip()

    existing_email = users_collection.find_one({
        "email": email
    })

    if existing_email:
        raise HTTPException(
            status_code=400,
            detail="Email is already registered",
        )

    hashed_password = hash_password(user.password)

    user_data = {
        "name": user.name,
        "employee_id": user.employee_id,
        "email": email,
        "role": user.role,
        "department": user.department,
        "password": hashed_password,
    }

    result = users_collection.insert_one(user_data)

    return {
        "message": "User created successfully",
        "user_id": str(result.inserted_id),
    }


# --------------------------------------------------
# LOGIN
# --------------------------------------------------

@router.post("/login")
def login(user: UserLogin, request: Request, response: Response):
    check_origin(request)
    if users_collection is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection is not available."
        )

    email = str(user.email).lower().strip()

    existing_user = users_collection.find_one({
        "email": email
    })

    if not existing_user:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    if not verify_password(
        user.password,
        existing_user["password"],
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    now = datetime.now(timezone.utc)
    # Rotate an existing cookie on login to prevent session fixation.
    previous_token = request.cookies.get(COOKIE_NAME)
    if previous_token:
        import hashlib
        sessions_collection.update_one(
            {"token_hash": hashlib.sha256(previous_token.encode()).hexdigest(), "ended_at": None},
            {"$set": {"ended_at": now}},
        )
    csrf_token = create_session(str(existing_user["_id"]), response)
    activity_collection.insert_one({
        "user_id": str(existing_user["_id"]), "type": "login",
        "ip_address": request.client.host if request.client else "Unknown",
        "created_at": now,
    })
    return {
        "message": "Login successful", "csrf_token": csrf_token,
        "user": public_user(existing_user),
    }


@router.get("/me")
def me(response: Response, session: dict = Depends(require_session)):
    response.headers["Cache-Control"] = "no-store"
    return {"user": session["user"], "csrf_token": session["csrf_token"]}
