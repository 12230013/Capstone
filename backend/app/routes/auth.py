
import os
import re
import hashlib
import secrets
import smtplib

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from app.schemas.user import UserCreate, UserLogin
from app.database.connection import (
    users_collection,
    password_reset_collection,
)
from app.utils.security import hash_password, verify_password


load_dotenv()

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
    otp: str


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    reset_token: str
    new_password: str


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

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, app_password)
        smtp.send_message(message)


def get_utc_datetime(value):
    """Ensure MongoDB datetimes are timezone-aware."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# --------------------------------------------------
# SIGNUP
# --------------------------------------------------

@router.post("/signup")
def signup(user: UserCreate):

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
def login(user: UserLogin):

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

    return {
        "message": "Login successful",
        "user": {
            "id": str(existing_user["_id"]),
            "name": existing_user["name"],
            "employee_id": existing_user["employee_id"],
            "email": existing_user["email"],
            "role": existing_user["role"],
            "department": existing_user["department"],
        },
    }


# --------------------------------------------------
# FORGOT PASSWORD: GENERATE AND SEND OTP
# --------------------------------------------------

@router.post("/forgot-password")
def forgot_password(request: ForgotPasswordRequest):

    email = str(request.email).lower().strip()

    # Return a generic response to avoid revealing
    # whether an email is registered.
    user = users_collection.find_one({"email": email})

    if user:
        otp = f"{secrets.randbelow(1_000_000):06d}"
        now = datetime.now(timezone.utc)

        # Remove any previous OTP for this email.
        password_reset_collection.delete_many({
            "email": email
        })

        password_reset_collection.insert_one({
            "email": email,
            "otp_hash": hash_value(otp),
            "created_at": now,
            "expires_at": now + timedelta(minutes=10),
            "attempts": 0,
            "verified": False,
        })

        try:
            send_otp_email(email, otp)

        except Exception:
            password_reset_collection.delete_many({
                "email": email
            })

            raise HTTPException(
                status_code=500,
                detail=(
                    "Unable to send the OTP email. "
                    "Please check the backend email configuration."
                ),
            )

    return {
        "message": (
            "If an account exists for that email, "
            "a password-reset OTP has been sent."
        )
    }


# --------------------------------------------------
# VERIFY OTP
# --------------------------------------------------

@router.post("/verify-otp")
def verify_otp(request: VerifyOTPRequest):

    email = str(request.email).lower().strip()

    # OTP must contain exactly six digits.
    if not re.fullmatch(r"\d{6}", request.otp):
        raise HTTPException(
            status_code=400,
            detail="Please enter a valid six-digit OTP.",
        )

    record = password_reset_collection.find_one({
        "email": email
    })

    if not record or record.get("verified", False):
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OTP. Please request a new one.",
        )

    now = datetime.now(timezone.utc)
    expiry = get_utc_datetime(record["expires_at"])

    if now >= expiry:
        password_reset_collection.delete_many({
            "email": email
        })

        raise HTTPException(
            status_code=400,
            detail="OTP has expired. Please request a new one.",
        )

    if record.get("attempts", 0) >= 5:
        password_reset_collection.delete_many({
            "email": email
        })

        raise HTTPException(
            status_code=400,
            detail="Too many incorrect attempts. Please request a new OTP.",
        )

    entered_hash = hash_value(request.otp)

    if not secrets.compare_digest(
        entered_hash,
        record["otp_hash"],
    ):
        password_reset_collection.update_one(
            {"_id": record["_id"]},
            {"$inc": {"attempts": 1}},
        )

        raise HTTPException(
            status_code=400,
            detail="Incorrect OTP. Please try again.",
        )

    # Generate a separate token for the password-reset step.
    reset_token = secrets.token_urlsafe(32)

    password_reset_collection.update_one(
        {"_id": record["_id"]},
        {
            "$set": {
                "verified": True,
                "reset_token_hash": hash_value(reset_token),
                "reset_expires_at": now + timedelta(minutes=10),
            },
            "$unset": {
                "otp_hash": "",
            },
        },
    )

    return {
        "message": "OTP verified successfully.",
        "reset_token": reset_token,
    }


# --------------------------------------------------
# RESET PASSWORD
# --------------------------------------------------

@router.post("/reset-password")
def reset_password(request: ResetPasswordRequest):

    email = str(request.email).lower().strip()

    if len(request.new_password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters long.",
        )

    record = password_reset_collection.find_one({
        "email": email,
        "verified": True,
        "reset_token_hash": hash_value(request.reset_token),
    })

    if not record:
        raise HTTPException(
            status_code=400,
            detail=(
                "Password reset session is invalid. "
                "Please verify your OTP again."
            ),
        )

    expiry = get_utc_datetime(record["reset_expires_at"])

    if datetime.now(timezone.utc) >= expiry:
        password_reset_collection.delete_many({
            "email": email
        })

        raise HTTPException(
            status_code=400,
            detail=(
                "Password reset session has expired. "
                "Please verify your OTP again."
            ),
        )

    # Store the new password using your existing hash function.
    result = users_collection.update_one(
        {"email": email},
        {
            "$set": {
                "password": hash_password(request.new_password)
            }
        },
    )

    if result.matched_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Unable to reset the password.",
        )

    # Delete the reset record so the token cannot be reused.
    password_reset_collection.delete_many({
        "email": email
    })

    return {
        "message": "Password reset successfully. Please log in."
    }