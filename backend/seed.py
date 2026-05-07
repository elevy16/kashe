"""Seed Kashé with demo users, boutique challenges, and partner rewards."""

from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from app import app, db
from models import Challenge, Enrollment, PointTxn, Redemption, Reward, User

with app.app_context():
    # Clear existing data (respect foreign keys)
    PointTxn.query.delete()
    Redemption.query.delete()
    Enrollment.query.delete()
    Reward.query.delete()
    Challenge.query.delete()
    User.query.delete()
    db.session.commit()

    now = datetime.utcnow()

    esther = User(
        name="Esther Levy",
        email="esther@test.com",
        password_hash=generate_password_hash("password123"),
    )
    riva = User(
        name="Riva Cohen",
        email="riva@test.com",
        password_hash=generate_password_hash("password123"),
    )
    leah = User(
        name="Leah Weiss",
        email="leah@test.com",
        password_hash=generate_password_hash("password123"),
    )
    db.session.add_all([esther, riva, leah])
    db.session.commit()

    challenges = [
        Challenge(
            title="Cardio Crush",
            required_classes=5,
            points_reward=100,
            is_active=True,
            deadline=now + timedelta(days=21),
        ),
        Challenge(
            title="Pilates Powerhouse",
            required_classes=6,
            points_reward=120,
            is_active=True,
            deadline=now + timedelta(days=28),
        ),
        Challenge(
            title="Strength & Sculpt",
            required_classes=8,
            points_reward=150,
            is_active=True,
            deadline=now + timedelta(days=35),
        ),
        Challenge(
            title="Yoga Flow Journey",
            required_classes=10,
            points_reward=200,
            is_active=True,
            deadline=now + timedelta(days=45),
        ),
        Challenge(
            title="HIIT Warrior",
            required_classes=4,
            points_reward=80,
            is_active=True,
            deadline=now + timedelta(days=14),
        ),
        Challenge(
            title="Barre Basics",
            required_classes=5,
            points_reward=100,
            is_active=True,
            deadline=now + timedelta(days=18),
        ),
    ]
    db.session.add_all(challenges)
    db.session.commit()

    by_title = {c.title: c for c in challenges}

    rewards = [
        Reward(title="Free Smoothie at Pressed Juicery", points_cost=75, is_active=True),
        Reward(title="$15 Lululemon Gift Card", points_cost=150, is_active=True),
        Reward(title="Free Class at SoulCycle", points_cost=200, is_active=True),
        Reward(title="Alo Yoga Water Bottle", points_cost=100, is_active=True),
        Reward(title="1 Month Spotify Premium", points_cost=125, is_active=True),
        Reward(title="$20 Sakara Life Credit", points_cost=175, is_active=True),
    ]
    db.session.add_all(rewards)
    db.session.commit()

    reward_alo = next(r for r in rewards if r.title == "Alo Yoga Water Bottle")

    # Esther — enrollments & activity
    db.session.add_all(
        [
            Enrollment(
                user_id=esther.id,
                challenge_id=by_title["Cardio Crush"].id,
                classes_completed=4,
                status="active",
            ),
            Enrollment(
                user_id=esther.id,
                challenge_id=by_title["Pilates Powerhouse"].id,
                classes_completed=2,
                status="active",
            ),
            Enrollment(
                user_id=esther.id,
                challenge_id=by_title["HIIT Warrior"].id,
                classes_completed=4,
                status="completed",
            ),
        ]
    )

    t0 = now - timedelta(days=10)
    db.session.add_all(
        [
            PointTxn(
                user_id=esther.id,
                delta=80,
                reason="Completed: HIIT Warrior",
                created_at=t0,
            ),
            PointTxn(
                user_id=esther.id,
                delta=50,
                reason="Welcome bonus — Kashé member perks",
                created_at=t0 + timedelta(hours=2),
            ),
        ]
    )
    db.session.flush()

    alo_code = "7c2f9ae1-b4d3-4e81-9f0a-1b2c3d4e5f67"
    db.session.add(
        Redemption(
            user_id=esther.id,
            reward_id=reward_alo.id,
            code=alo_code,
            redeemed_at=t0 + timedelta(days=1),
        )
    )
    db.session.add(
        PointTxn(
            user_id=esther.id,
            delta=-100,
            reason="Redeemed: Alo Yoga Water Bottle",
            created_at=t0 + timedelta(days=1, minutes=1),
        )
    )

    # Riva — enrollments & activity
    db.session.add_all(
        [
            Enrollment(
                user_id=riva.id,
                challenge_id=by_title["Yoga Flow Journey"].id,
                classes_completed=7,
                status="active",
            ),
            Enrollment(
                user_id=riva.id,
                challenge_id=by_title["Barre Basics"].id,
                classes_completed=5,
                status="completed",
            ),
        ]
    )
    db.session.add(
        PointTxn(
            user_id=riva.id,
            delta=100,
            reason="Completed: Barre Basics",
            created_at=now - timedelta(days=3),
        )
    )

    db.session.commit()

    print("Database seeded successfully!")
