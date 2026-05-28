"""Seed Kashé with demo data for a boutique fitness loyalty presentation."""

from datetime import datetime, timedelta

from sqlalchemy import func
from werkzeug.security import generate_password_hash

from app import app, db
from models import Challenge, Enrollment, PointTxn, Redemption, Reward, User

PASSWORD = "password123"


def _balance(user_id: int) -> int:
    return int(
        db.session.query(func.sum(PointTxn.delta)).filter_by(user_id=user_id).scalar()
        or 0
    )


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
    weeks = lambda n: now + timedelta(weeks=n)

    esther = User(
        name="Esther Levy",
        email="esther@test.com",
        password_hash=generate_password_hash(PASSWORD),
        created_at=now - timedelta(days=95),
    )
    sara = User(
        name="Sara Cohen",
        email="sara@test.com",
        password_hash=generate_password_hash(PASSWORD),
        created_at=now - timedelta(days=60),
    )
    mia = User(
        name="Mia Rodriguez",
        email="mia@test.com",
        password_hash=generate_password_hash(PASSWORD),
        created_at=now - timedelta(days=30),
    )
    db.session.add_all([esther, sara, mia])
    db.session.commit()

    challenges = [
        Challenge(
            title="Cardio Crush",
            required_classes=5,
            points_reward=100,
            is_active=True,
            deadline=weeks(4),
        ),
        Challenge(
            title="Pilates Powerhouse",
            required_classes=6,
            points_reward=120,
            is_active=True,
            deadline=weeks(5),
        ),
        Challenge(
            title="Strength & Sculpt",
            required_classes=8,
            points_reward=150,
            is_active=True,
            deadline=weeks(6),
        ),
        Challenge(
            title="Yoga Flow Journey",
            required_classes=10,
            points_reward=200,
            is_active=True,
            deadline=weeks(6),
        ),
        Challenge(
            title="HIIT Warrior",
            required_classes=4,
            points_reward=80,
            is_active=True,
            deadline=weeks(3),
        ),
        Challenge(
            title="Barre Basics",
            required_classes=5,
            points_reward=100,
            is_active=True,
            deadline=weeks(3),
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

    reward_smoothie = next(r for r in rewards if "Pressed Juicery" in r.title)
    reward_alo = next(r for r in rewards if r.title == "Alo Yoga Water Bottle")

    # --- Esther: power user, several wins, two redemptions, three active streaks ---
    t_join = now - timedelta(days=90)

    db.session.add_all(
        [
            # Completed challenges
            Enrollment(
                user_id=esther.id,
                challenge_id=by_title["HIIT Warrior"].id,
                classes_completed=4,
                status="completed",
                created_at=t_join,
            ),
            Enrollment(
                user_id=esther.id,
                challenge_id=by_title["Cardio Crush"].id,
                classes_completed=5,
                status="completed",
                created_at=t_join + timedelta(days=5),
            ),
            Enrollment(
                user_id=esther.id,
                challenge_id=by_title["Barre Basics"].id,
                classes_completed=5,
                status="completed",
                created_at=t_join + timedelta(days=12),
            ),
            # Almost there & in progress
            Enrollment(
                user_id=esther.id,
                challenge_id=by_title["Pilates Powerhouse"].id,
                classes_completed=4,
                status="active",
                created_at=now - timedelta(days=25),
            ),
            Enrollment(
                user_id=esther.id,
                challenge_id=by_title["Yoga Flow Journey"].id,
                classes_completed=7,
                status="active",
                created_at=now - timedelta(days=40),
            ),
            Enrollment(
                user_id=esther.id,
                challenge_id=by_title["Strength & Sculpt"].id,
                classes_completed=2,
                status="active",
                created_at=now - timedelta(days=14),
            ),
        ]
    )

    db.session.add_all(
        [
            PointTxn(
                user_id=esther.id,
                delta=50,
                reason="Welcome bonus — Kashé member perks",
                created_at=t_join,
            ),
            PointTxn(
                user_id=esther.id,
                delta=80,
                reason="Completed: HIIT Warrior",
                created_at=t_join + timedelta(days=18),
            ),
            PointTxn(
                user_id=esther.id,
                delta=100,
                reason="Completed: Cardio Crush",
                created_at=t_join + timedelta(days=35),
            ),
            PointTxn(
                user_id=esther.id,
                delta=100,
                reason="Completed: Barre Basics",
                created_at=t_join + timedelta(days=52),
            ),
        ]
    )
    db.session.flush()

    db.session.add(
        Redemption(
            user_id=esther.id,
            reward_id=reward_smoothie.id,
            code="KSH-SMOOTHIE-2026",
            redeemed_at=now - timedelta(days=20),
        )
    )
    db.session.add(
        PointTxn(
            user_id=esther.id,
            delta=-75,
            reason="Redeemed: Free Smoothie at Pressed Juicery",
            created_at=now - timedelta(days=20, minutes=2),
        )
    )

    db.session.add(
        Redemption(
            user_id=esther.id,
            reward_id=reward_alo.id,
            code="KSH-ALOYOGA-2026",
            redeemed_at=now - timedelta(days=8),
        )
    )
    db.session.add(
        PointTxn(
            user_id=esther.id,
            delta=-100,
            reason="Redeemed: Alo Yoga Water Bottle",
            created_at=now - timedelta(days=8, minutes=2),
        )
    )

    # --- Sara: strong on yoga & cardio, finished Pilates ---
    sara_start = now - timedelta(days=45)

    db.session.add_all(
        [
            Enrollment(
                user_id=sara.id,
                challenge_id=by_title["Pilates Powerhouse"].id,
                classes_completed=6,
                status="completed",
                created_at=sara_start,
            ),
            Enrollment(
                user_id=sara.id,
                challenge_id=by_title["Yoga Flow Journey"].id,
                classes_completed=5,
                status="active",
                created_at=sara_start + timedelta(days=10),
            ),
            Enrollment(
                user_id=sara.id,
                challenge_id=by_title["Cardio Crush"].id,
                classes_completed=3,
                status="active",
                created_at=now - timedelta(days=12),
            ),
        ]
    )
    db.session.add(
        PointTxn(
            user_id=sara.id,
            delta=120,
            reason="Completed: Pilates Powerhouse",
            created_at=now - timedelta(days=5),
        )
    )

    # --- Mia: newer member, early momentum ---
    db.session.add(
        Enrollment(
            user_id=mia.id,
            challenge_id=by_title["HIIT Warrior"].id,
            classes_completed=2,
            status="active",
            created_at=now - timedelta(days=10),
        )
    )
    db.session.add(
        PointTxn(
            user_id=mia.id,
            delta=50,
            reason="Welcome bonus — Kashé member perks",
            created_at=now - timedelta(days=10),
        )
    )

    db.session.commit()

    print("Database seeded successfully!\n")
    print("Demo login: esther@test.com / sara@test.com / mia@test.com — password: password123\n")
    print("—" * 50)
    print("User balances (from point transactions)")
    print("—" * 50)
    for user in (esther, sara, mia):
        bal = _balance(user.id)
        print(f"  {user.name:<18} {user.email:<22} {bal:>4} pts")
    print("—" * 50)
    print("\nEsther's story at a glance:")
    print("  ✓ Completed: HIIT Warrior, Cardio Crush, Barre Basics")
    print("  → In progress: Pilates (4/6), Yoga Flow (7/10), Strength (2/8)")
    print("  🎁 Redeemed: Pressed Juicery smoothie, Alo Yoga water bottle")
    print(f"  Expected balance: 155 pts (actual: {_balance(esther.id)} pts)")
    print("\nSara's story at a glance:")
    print("  ✓ Completed: Pilates Powerhouse")
    print("  → In progress: Yoga Flow (5/10), Cardio Crush (3/5)")
    print(f"  Expected balance: 120 pts (actual: {_balance(sara.id)} pts)")
