
from fastapi import HTTPException, Path


def validate_target_number(
    number: str = Path(..., description="Target phone number"),
) -> str:
    if not number.isascii() or not number.isdigit():
        raise HTTPException(
            status_code=400,
            detail="Invalid phone number. Number must contain digits only; letters and symbols are not allowed.",
        )

    if len(number) < 8:
        raise HTTPException(
            status_code=400,
            detail="Phone number is too short. It must be exactly 8 digits.",
        )

    if len(number) > 8:
        raise HTTPException(
            status_code=400,
            detail="Phone number is too long. It must be exactly 8 digits.",
        )

    return number
