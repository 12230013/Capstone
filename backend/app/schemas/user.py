from pydantic import BaseModel, EmailStr, Field, field_validator
import re


class UserCreate(BaseModel):

    name: str = Field(min_length=2, max_length=100)

    employee_id: str = Field(min_length=2, max_length=20)

    email: EmailStr

    role: str

    department: str = Field(min_length=2, max_length=100)

    password: str = Field(min_length=8, max_length=128)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        value = value.strip()

        if not re.match(r"^[A-Za-z\s]+$", value):
            raise ValueError("Name can only contain letters and spaces")

        return value

    @field_validator("employee_id")
    @classmethod
    def validate_employee_id(cls, value):
        value = value.strip().upper()

        if not re.match(r"^[A-Z0-9-]+$", value):
            raise ValueError(
                "Employee ID can only contain letters, numbers, and hyphens"
            )

        return value

    @field_validator("role")
    @classmethod
    def validate_role(cls, value):

        allowed_roles = {
            "Admin",
            "Director",
            "Investigator",
            "Team Members"
        }

        if value not in allowed_roles:
            raise ValueError("Invalid role selected")

        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value):

        if not re.search(r"[A-Z]", value):
            raise ValueError(
                "Password must contain at least one uppercase letter"
            )

        if not re.search(r"[a-z]", value):
            raise ValueError(
                "Password must contain at least one lowercase letter"
            )

        if not re.search(r"\d", value):
            raise ValueError(
                "Password must contain at least one number"
            )

        if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-]", value):
            raise ValueError(
                "Password must contain at least one special character"
            )

        return value


class UserLogin(BaseModel):

    email: EmailStr

    password: str = Field(min_length=1, max_length=128)