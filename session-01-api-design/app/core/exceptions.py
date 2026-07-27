from fastapi import HTTPException, status


class EmailAlreadyExistsError(HTTPException):
    """Raised when a user attempts to create an account with an existing email."""

    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")


class UserNotFoundError(HTTPException):
    """Raised when a requested user cannot be found."""

    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
