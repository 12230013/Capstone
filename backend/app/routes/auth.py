from fastapi import APIRouter, HTTPException

from app.schemas.user import UserCreate, UserLogin
from app.database.connection import users_collection
from app.utils.security import hash_password, verify_password


router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"]
)


@router.post("/signup")
def signup(user: UserCreate):

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
def login(user: UserLogin):

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

    # Login successful
    return {
        "message": "Login successful",
        "user": {
            "id": str(existing_user["_id"]),
            "name": existing_user["name"],
            "employee_id": existing_user["employee_id"],
            "email": existing_user["email"],
            "role": existing_user["role"],
            "department": existing_user["department"]
        }
    }