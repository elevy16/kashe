import os

from werkzeug.security import generate_password_hash

from app import app, db
from models import User, Challenge, Enrollment, PointTxn, Reward

with app.app_context():
    # Clear existing data in the specified order to avoid foreign key conflicts
    PointTxn.query.delete()
    Enrollment.query.delete()
    Reward.query.delete()
    Challenge.query.delete()
    User.query.delete()
    db.session.commit()

    # Create 2 fake users
    user1 = User(
        name="Esther",
        email="esther@test.com",
        password_hash=generate_password_hash("password123")
    )
    user2 = User(
        name="Sara",
        email="sara@test.com",
        password_hash=generate_password_hash("password123")
    )
    db.session.add(user1)
    db.session.add(user2)
    db.session.commit()

    # Create 3 fake challenges
    challenge1 = Challenge(
        title="Cardio Crush",
        required_classes=5,
        points_reward=100,
        is_active=True
    )
    challenge2 = Challenge(
        title="Studio Explorer",
        required_classes=3,
        points_reward=75,
        is_active=True
    )
    challenge3 = Challenge(
        title="Strength Builder",
        required_classes=8,
        points_reward=150,
        is_active=True
    )
    db.session.add(challenge1)
    db.session.add(challenge2)
    db.session.add(challenge3)
    db.session.commit()

    # Create 2 fake rewards
    reward1 = Reward(
        title="Free Smoothie",
        points_cost=50,
        is_active=True
    )
    reward2 = Reward(
        title="$10 Lululemon Gift Card",
        points_cost=100,
        is_active=True
    )
    db.session.add(reward1)
    db.session.add(reward2)
    db.session.commit()

    # Enroll Esther in "Cardio Crush" with classes_completed=3, status='active'
    enrollment = Enrollment(
        user_id=user1.id,
        challenge_id=challenge1.id,
        classes_completed=3,
        status='active'
    )
    db.session.add(enrollment)

    # Add a PointTxn for Esther with delta=75, reason="Completed: Studio Explorer"
    txn = PointTxn(
        user_id=user1.id,
        delta=75,
        reason="Completed: Studio Explorer"
    )
    db.session.add(txn)

    db.session.commit()

    print("Database seeded successfully!")