from fastapi import APIRouter, Depends, HTTPException, Request, Response
from datetime import datetime, timezone
from app.database.connection import sessions_collection, activity_collection

from app.schemas.user import UserCreate, UserLogin
from app.database.connection import users_collection
from app.utils.security import hash_password, verify_password
from app.utils.sessions import create_session, require_session, public_user, check_origin, COOKIE_NAME


router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"]
)


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
            detail="Employee ID is already registered"
        )

    existing_email = users_collection.find_one({
        "email": str(user.email)
    })

    if existing_email:
        raise HTTPException(
            status_code=400,
            detail="Email is already registered"
        )

    hashed_password = hash_password(user.password)

    user_data = {
        "name": user.name,
        "employee_id": user.employee_id,
        "email": str(user.email),
        "role": user.role,
        "department": user.department,
        "password": hashed_password
    }

    result = users_collection.insert_one(user_data)

    return {
        "message": "User created successfully",
        "user_id": str(result.inserted_id)
    }


@router.post("/login")
def login(user: UserLogin, request: Request, response: Response):
    check_origin(request)
    if users_collection is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection is not available."
        )

    # Find user by email
    existing_user = users_collection.find_one({
        "email": str(user.email)
    })

    # Do not reveal whether the email exists
    if not existing_user:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    # Verify entered password against stored password hash
    if not verify_password(
        user.password,
        existing_user["password"]
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
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
