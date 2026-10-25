# tests/test_email_normalization.py
# Email normalization: registration, login and duplicate detection.
#
# Coverage for the canonical form of an email address (trimmed, lowercased):
#   * registration stores the normalized address and keeps its response shape;
#   * a mailbox cannot be registered twice, whatever the case or spacing of
#     the second spelling;
#   * login succeeds for any casing/spacing of a registered address;
#   * a wrong password is still rejected with the same 401 response;
#   * an account created before normalization existed (a mixed-case row) stays
#     usable and still blocks a second registration of the same mailbox.
#
# Isolated temporary-SQLite setup (same pattern as
# test_cleaner_location_access.py): every test gets its own throwaway
# database, so the real smarttracker.db is never touched.

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from backend.database import _create_database_engine, get_db, run_migrations  # noqa: E402
from backend.models import User  # noqa: E402
from backend.main import app  # noqa: E402
from backend.routers.auth import SECRET_KEY, hash_password  # noqa: E402
from backend.schemas import normalize_email  # noqa: E402

PASSWORD = "Password123!"


@pytest.fixture
def client_and_db(tmp_path):
    engine = _create_database_engine(
        f"sqlite:///{tmp_path / 'email_normalization.db'}",
        connect_args={"check_same_thread": False},
    )
    run_migrations(target_engine=engine)
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        yield client, session_factory
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        client.close()
        engine.dispose()


def _register(client, email, name="Test User", password=PASSWORD):
    return client.post(
        "/auth/register",
        json={"name": name, "email": email, "password": password},
    )


def _login(client, email, password=PASSWORD):
    return client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )


def _stored_emails(session_factory):
    with session_factory() as db:
        return [row[0] for row in db.query(User.email).order_by(User.id).all()]


def test_normalize_email_trims_and_lowercases():
    assert normalize_email("  User@Example.COM  ") == "user@example.com"
    assert normalize_email("user@example.com") == "user@example.com"
    assert normalize_email(" user@example.com ") == "user@example.com"
    assert normalize_email("USER@EXAMPLE.COM") == "user@example.com"


def test_register_stores_the_normalized_email(client_and_db):
    client, session_factory = client_and_db

    response = _register(client, "  User@Example.COM  ")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "user@example.com"
    assert body["name"] == "Test User"
    assert body["role"] == "citizen"
    assert isinstance(body["id"], int)
    assert _stored_emails(session_factory) == ["user@example.com"]


def test_duplicate_registration_is_rejected_across_case_and_spacing(client_and_db):
    client, session_factory = client_and_db
    assert _register(client, "user@example.com").status_code == 201

    for variant in [
        "USER@EXAMPLE.COM",
        "User@Example.com",
        " user@example.com ",
        "  user@example.com  ",
    ]:
        response = _register(client, variant)
        assert response.status_code == 400, f"{variant!r} -> {response.status_code}"
        assert response.json()["detail"] == (
            "An account with this email address already exists."
        )

    # No second account was created for the same mailbox.
    assert _stored_emails(session_factory) == ["user@example.com"]


def test_login_succeeds_with_different_casing_and_spacing(client_and_db):
    client, _ = client_and_db
    assert _register(client, "User@Example.com").status_code == 201

    for variant in [
        "user@example.com",
        "USER@EXAMPLE.COM",
        "  user@example.com  ",
        "User@example.com",
    ]:
        response = _login(client, variant)
        assert response.status_code == 200, f"{variant!r} -> {response.status_code}"
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]


def test_login_with_an_incorrect_password_is_rejected(client_and_db):
    client, _ = client_and_db
    assert _register(client, "user@example.com").status_code == 201

    wrong_password = _login(client, "user@example.com", "WrongPassword9!")
    assert wrong_password.status_code == 401
    assert wrong_password.json()["detail"] == "Incorrect email or password."
    assert wrong_password.headers["www-authenticate"] == "Bearer"

    # An unknown address gets the very same response, so accounts cannot be
    # enumerated through the login endpoint.
    unknown = _login(client, "nobody@example.com", PASSWORD)
    assert unknown.status_code == 401
    assert unknown.json()["detail"] == "Incorrect email or password."


def test_legacy_mixed_case_row_can_log_in_and_blocks_a_new_duplicate(client_and_db):
    client, session_factory = client_and_db

    # A row created before email normalization existed: mixed case, kept as-is.
    with session_factory() as db:
        db.add(
            User(
                name="Legacy User",
                email="Legacy.User@Example.com",
                password_hash=hash_password(PASSWORD),
                role="citizen",
            )
        )
        db.commit()

    response = _login(client, "legacy.user@example.com")
    assert response.status_code == 200, response.text
    assert response.json()["token_type"] == "bearer"

    # The same mailbox cannot be registered a second time, in any spelling.
    for variant in ["LEGACY.USER@EXAMPLE.COM", "legacy.user@example.com"]:
        duplicate = _register(client, variant)
        assert duplicate.status_code == 400
        assert duplicate.json()["detail"] == (
            "An account with this email address already exists."
        )

    # The legacy row is untouched and no extra account appeared.
    assert _stored_emails(session_factory) == ["Legacy.User@Example.com"]


def test_registration_and_login_keep_their_response_shapes(client_and_db):
    client, _ = client_and_db

    registered = _register(client, "Shape.User@Example.com")
    assert registered.status_code == 201, registered.text
    body = registered.json()
    assert set(body) == {"id", "name", "email", "role"}
    assert body["role"] == "citizen"

    logged_in = _login(client, "shape.user@example.com")
    assert logged_in.status_code == 200, logged_in.text
    token = logged_in.json()
    assert set(token) == {"access_token", "token_type"}
    assert token["token_type"] == "bearer"

    # The token still carries the citizen role.
    claims = jwt.decode(token["access_token"], SECRET_KEY, algorithms=["HS256"])
    assert claims["role"] == "citizen"
    assert claims["sub"] == str(body["id"])
