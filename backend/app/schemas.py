from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if value.count("@") != 1 or "." not in value.split("@")[-1] or any(c.isspace() for c in value):
            raise ValueError("Enter a valid email address")
        return value


class Register(Login):
    business_name: str = Field(min_length=2, max_length=120)
    industry: Literal["ecommerce", "appointments"]


class BusinessProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    industry: str
    currency: str
    monthly_budget: Decimal
    goals: list[str]
    constraints: list[str]
    description: str


class ProfileUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    monthly_budget: Decimal = Field(ge=0, le=1_000_000_000, max_digits=14, decimal_places=2)
    goals: list[str] = Field(max_length=20)
    constraints: list[str] = Field(max_length=20)
    description: str = Field(max_length=2000)

    @field_validator("goals", "constraints")
    @classmethod
    def validate_lines(cls, value: list[str]) -> list[str]:
        if any(len(line) > 300 for line in value):
            raise ValueError("Each goal or constraint must be at most 300 characters")
        return [line.strip() for line in value if line.strip()]


class InvestigationRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)

    @field_validator("question")
    @classmethod
    def trim_question(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Enter a question with at least 3 characters")
        return value


class KnowledgeSearch(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def trim_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter a search query")
        return value
