"""API tests using pytest-flask (FlaskClient / ``client`` fixture)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

# Resolve backend package root so ``import app`` works when pytest cwd is ``backend/`` or repo root.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


@pytest.fixture
def app():
    """Flask application with in-memory SQLite; tables created per test, dropped after."""
    from app import app as application
    from extensions import db
    import models  # noqa: F401 — register models with SQLAlchemy metadata

    # StaticPool + :memory: shares one DB across pooled connections (Flask client vs app_context).
    application.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_ENGINE_OPTIONS={
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        },
        TESTING=True,
        JWT_SECRET_KEY="test-jwt-secret-for-pytest",
    )

    with application.app_context():
        db.session.remove()
        db.engine.dispose()
        db.create_all()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture
def auth_token(client):
    """Register a default test user, log in, return JWT access token."""
    client.post(
        "/api/register",
        json={
            "name": "Test User",
            "email": "testuser@example.com",
            "password": "correct-password",
        },
    )
    resp = client.post(
        "/api/login",
        json={"email": "testuser@example.com", "password": "correct-password"},
    )
    assert resp.status_code == 200
    return resp.get_json()["token"]


@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def seeded_challenges_and_rewards(app):
    """One active challenge and two rewards for balance / redeem / enroll flows."""
    from extensions import db
    from models import Challenge, Reward

    with app.app_context():
        db.session.add(
            Challenge(
                title="Studio streak",
                required_classes=3,
                points_reward=100,
                is_active=True,
            )
        )
        db.session.add(
            Reward(title="Small treat", points_cost=30, is_active=True),
        )
        db.session.add(
            Reward(title="Big prize", points_cost=1000, is_active=True),
        )
        db.session.commit()
        challenge_id = Challenge.query.filter_by(title="Studio streak").first().id
        small = Reward.query.filter_by(title="Small treat").first()
        big = Reward.query.filter_by(title="Big prize").first()
        return {"challenge_id": challenge_id, "small_reward_id": small.id, "big_reward_id": big.id}


# --- POST /api/register ---


def test_register_success(client):
    resp = client.post(
        "/api/register",
        json={
            "name": "Alice",
            "email": "alice@example.com",
            "password": "hunter2",
        },
    )
    assert resp.status_code == 201
    assert resp.get_json().get("message")


def test_register_duplicate_email(client):
    body = {"name": "A", "email": "dup@example.com", "password": "p"}
    assert client.post("/api/register", json=body).status_code == 201
    resp = client.post("/api/register", json=body)
    assert resp.status_code == 409
    assert "error" in resp.get_json()


# --- POST /api/login ---


def test_login_success(client):
    client.post(
        "/api/register",
        json={"name": "Bob", "email": "bob@example.com", "password": "secret"},
    )
    resp = client.post(
        "/api/login",
        json={"email": "bob@example.com", "password": "secret"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "token" in data
    assert data["name"] == "Bob"
    assert data["email"] == "bob@example.com"


def test_login_wrong_password(client):
    client.post(
        "/api/register",
        json={"name": "C", "email": "c@example.com", "password": "right"},
    )
    resp = client.post(
        "/api/login",
        json={"email": "c@example.com", "password": "wrong"},
    )
    assert resp.status_code == 401


def test_login_missing_fields(client):
    assert client.post("/api/login", json={}).status_code == 400
    assert client.post("/api/login", json={"email": "x@y.com"}).status_code == 400


# --- GET /api/challenges ---


def test_get_challenges_requires_auth(client):
    resp = client.get("/api/challenges")
    assert resp.status_code == 401


def test_get_challenges_with_auth(client, auth_headers, seeded_challenges_and_rewards):
    resp = client.get("/api/challenges", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert len(data) >= 1
    row = next(c for c in data if c["title"] == "Studio streak")
    assert row["required_classes"] == 3
    assert row["points_reward"] == 100


# --- POST /api/enroll ---


def test_enroll_success(client, auth_headers, seeded_challenges_and_rewards):
    cid = seeded_challenges_and_rewards["challenge_id"]
    resp = client.post(
        "/api/enroll",
        json={"challenge_id": cid},
        headers=auth_headers,
    )
    assert resp.status_code == 201


def test_enroll_duplicate(client, auth_headers, seeded_challenges_and_rewards):
    cid = seeded_challenges_and_rewards["challenge_id"]
    headers = auth_headers
    assert client.post("/api/enroll", json={"challenge_id": cid}, headers=headers).status_code == 201
    resp = client.post("/api/enroll", json={"challenge_id": cid}, headers=headers)
    assert resp.status_code == 409


def test_enroll_invalid_challenge(client, auth_headers):
    resp = client.post(
        "/api/enroll",
        json={"challenge_id": 99999},
        headers=auth_headers,
    )
    assert resp.status_code == 404


# --- POST /api/checkin ---


def test_checkin_increments_classes_completed(client, app, auth_headers, seeded_challenges_and_rewards):
    from extensions import db
    from models import Enrollment, User

    cid = seeded_challenges_and_rewards["challenge_id"]
    client.post("/api/enroll", json={"challenge_id": cid}, headers=auth_headers)

    with app.app_context():
        user = User.query.filter_by(email="testuser@example.com").first()
        uid = user.id
        enr = Enrollment.query.filter_by(user_id=uid, challenge_id=cid).first()
        eid = enr.id
        assert enr.classes_completed == 0

    resp = client.post(
        "/api/checkin",
        json={"enrollment_id": eid},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.get_json()["classes_completed"] == 1

    with app.app_context():
        enr = Enrollment.query.get(eid)
        assert enr.classes_completed == 1


def test_checkin_already_completed(client, auth_headers, seeded_challenges_and_rewards):
    from extensions import db
    from models import Challenge, Enrollment, User

    cid = seeded_challenges_and_rewards["challenge_id"]
    with client.application.app_context():
        ch = Challenge.query.get(cid)
        ch.required_classes = 1
        db.session.commit()

    client.post("/api/enroll", json={"challenge_id": cid}, headers=auth_headers)

    with client.application.app_context():
        user = User.query.filter_by(email="testuser@example.com").first()
        eid = Enrollment.query.filter_by(user_id=user.id, challenge_id=cid).first().id

    assert client.post(
        "/api/checkin",
        json={"enrollment_id": eid},
        headers=auth_headers,
    ).status_code == 200

    resp = client.post(
        "/api/checkin",
        json={"enrollment_id": eid},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_checkin_wrong_user(client, auth_headers, seeded_challenges_and_rewards):
    cid = seeded_challenges_and_rewards["challenge_id"]
    client.post("/api/enroll", json={"challenge_id": cid}, headers=auth_headers)

    with client.application.app_context():
        from models import Enrollment, User

        user1 = User.query.filter_by(email="testuser@example.com").first()
        eid = Enrollment.query.filter_by(user_id=user1.id, challenge_id=cid).first().id

    client.post(
        "/api/register",
        json={"name": "Other", "email": "other@example.com", "password": "pw"},
    )
    r2 = client.post(
        "/api/login",
        json={"email": "other@example.com", "password": "pw"},
    )
    token2 = r2.get_json()["token"]

    resp = client.post(
        "/api/checkin",
        json={"enrollment_id": eid},
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert resp.status_code == 404


# --- GET /api/rewards ---


def test_get_rewards_balance_and_can_afford(client, app, auth_headers, seeded_challenges_and_rewards):
    from extensions import db
    from models import PointTxn, User

    small_id = seeded_challenges_and_rewards["small_reward_id"]
    big_id = seeded_challenges_and_rewards["big_reward_id"]

    with app.app_context():
        user = User.query.filter_by(email="testuser@example.com").first()
        db.session.add(PointTxn(user_id=user.id, delta=50, reason="Test grant"))
        db.session.commit()

    resp = client.get("/api/rewards", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["balance"] == 50
    rewards = {r["id"]: r for r in data["rewards"]}
    assert rewards[small_id]["can_afford"] is True
    assert rewards[big_id]["can_afford"] is False


# --- POST /api/redeem ---


def test_redeem_success(client, app, auth_headers, seeded_challenges_and_rewards):
    from extensions import db
    from models import PointTxn, User

    rid = seeded_challenges_and_rewards["small_reward_id"]
    with app.app_context():
        user = User.query.filter_by(email="testuser@example.com").first()
        db.session.add(PointTxn(user_id=user.id, delta=100, reason="Bank"))
        db.session.commit()

    resp = client.post(
        "/api/redeem",
        json={"reward_id": rid},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert "code" in body
    assert body.get("reward_title") == "Small treat"


def test_redeem_insufficient_points(client, auth_headers, seeded_challenges_and_rewards):
    rid = seeded_challenges_and_rewards["big_reward_id"]
    resp = client.post(
        "/api/redeem",
        json={"reward_id": rid},
        headers=auth_headers,
    )
    assert resp.status_code == 400


# --- GET /api/enrollments ---


def test_get_enrollments(client, auth_headers, seeded_challenges_and_rewards):
    cid = seeded_challenges_and_rewards["challenge_id"]
    client.post("/api/enroll", json={"challenge_id": cid}, headers=auth_headers)

    resp = client.get("/api/enrollments", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["challenge_id"] == cid
    assert data[0]["classes_completed"] == 0


# --- GET /api/profile/stats ---


def test_profile_stats(client, app, auth_headers, seeded_challenges_and_rewards):
    from extensions import db
    from models import Challenge, Enrollment, PointTxn, Redemption, User

    cid = seeded_challenges_and_rewards["challenge_id"]
    rid = seeded_challenges_and_rewards["small_reward_id"]

    with app.app_context():
        user = User.query.filter_by(email="testuser@example.com").first()
        ch = Challenge.query.get(cid)
        ch.required_classes = 1
        db.session.add(
            Enrollment(
                user_id=user.id,
                challenge_id=cid,
                classes_completed=1,
                status="completed",
            )
        )
        db.session.add(PointTxn(user_id=user.id, delta=100, reason="Done"))
        db.session.add(Redemption(user_id=user.id, reward_id=rid, code="test-code-unique-1"))
        db.session.commit()

    resp = client.get("/api/profile/stats", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["challenges_completed"] == 1
    assert data["rewards_redeemed"] == 1


# --- GET /api/point_txns/lifetime ---


def test_lifetime_points(client, app, auth_headers):
    from extensions import db
    from models import PointTxn, User

    with app.app_context():
        user = User.query.filter_by(email="testuser@example.com").first()
        db.session.add(PointTxn(user_id=user.id, delta=100, reason="Earned"))
        db.session.add(PointTxn(user_id=user.id, delta=50, reason="Earned 2"))
        db.session.add(PointTxn(user_id=user.id, delta=-30, reason="Redeemed"))
        db.session.commit()

    resp = client.get("/api/point_txns/lifetime", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()["lifetime_points"] == 150
