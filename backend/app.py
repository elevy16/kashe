import os
import uuid

from flask import Flask, jsonify, request
from flask_jwt_extended import create_access_token
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import func

from extensions import db, jwt

from models import Challenge, Enrollment, PointTxn, Reward, Redemption
from flask_jwt_extended import jwt_required, get_jwt_identity
from flask_cors import CORS


app = Flask(__name__)

CORS(app, origins=["http://localhost:5173"])

app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", "sqlite:///kashe_dev.db"
)
app.config["JWT_SECRET_KEY"] = os.getenv(
    "JWT_SECRET_KEY", "dev-secret-change-in-production"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize extensions
db.init_app(app)
jwt.init_app(app)

# Import models after extensions are initialized to avoid circular imports
import models  # noqa: F401

# Ensure tables are created on startup
with app.app_context():
    db.create_all()


@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "ok", "app": "Kashé API"})


@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    name = data.get("name")
    email = data.get("email")
    password = data.get("password")

    if not name or not email or not password:
        return jsonify({"error": "Name, email, and password are required"}), 400

    existing = models.User.query.filter_by(email=email).first()
    if existing:
        return jsonify({"error": "Email already registered"}), 409

    password_hash = generate_password_hash(password)
    user = models.User(name=name, email=email, password_hash=password_hash)
    db.session.add(user)
    db.session.commit()

    return jsonify({"message": "User created successfully"}), 201


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    user = models.User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Invalid credentials"}), 401

    token = create_access_token(identity=str(user.id))
    return jsonify({"token": token}), 200


@app.route('/api/challenges', methods=['GET'])
@jwt_required()
def get_challenges():
    challenges = Challenge.query.filter_by(is_active=True).all()
    result = []
    for challenge in challenges:
        result.append({
            'id': challenge.id,
            'title': challenge.title,
            'required_classes': challenge.required_classes,
            'points_reward': challenge.points_reward,
            'deadline': str(challenge.deadline) if challenge.deadline else None
        })
    return jsonify(result)


@app.route('/api/enroll', methods=['POST'])
@jwt_required()
def enroll():
    data = request.get_json() or {}
    challenge_id = data.get('challenge_id')
    if not challenge_id:
        return jsonify({"error": "challenge_id is required"}), 400

    user_id = get_jwt_identity()
    challenge = Challenge.query.filter_by(id=challenge_id, is_active=True).first()
    if not challenge:
        return jsonify({"error": "Challenge not found or inactive"}), 404

    existing_enrollment = Enrollment.query.filter_by(user_id=user_id, challenge_id=challenge_id).first()
    if existing_enrollment:
        return jsonify({"error": "Already enrolled"}), 409

    enrollment = Enrollment(user_id=user_id, challenge_id=challenge_id, classes_completed=0, status='active')
    db.session.add(enrollment)
    db.session.commit()
    return jsonify({"message": "Enrolled successfully"}), 201


@app.route('/api/checkin', methods=['POST'])
@jwt_required()
def checkin():
    data = request.get_json() or {}
    enrollment_id = data.get('enrollment_id')
    if not enrollment_id:
        return jsonify({"error": "enrollment_id is required"}), 400

    user_id = get_jwt_identity()
    enrollment = Enrollment.query.filter_by(id=enrollment_id, user_id=user_id).first()
    if not enrollment:
        return jsonify({"error": "Enrollment not found"}), 404

    if enrollment.status == 'completed':
        return jsonify({"error": "Challenge already completed"}), 400

    enrollment.classes_completed += 1
    completed = False
    points_earned = 0
    challenge = Challenge.query.get(enrollment.challenge_id)
    if enrollment.classes_completed >= challenge.required_classes:
        enrollment.status = 'completed'
        completed = True
        points_earned = challenge.points_reward
        txn = PointTxn(user_id=user_id, delta=points_earned, reason=f"Completed: {challenge.title}")
        db.session.add(txn)

    db.session.commit()
    return jsonify({
        "classes_completed": enrollment.classes_completed,
        "completed": completed,
        "points_earned": points_earned
    })


@app.route('/api/rewards', methods=['GET'])
@jwt_required()
def get_rewards():
    user_id = get_jwt_identity()
    balance = db.session.query(func.sum(PointTxn.delta)).filter_by(user_id=user_id).scalar() or 0
    rewards = Reward.query.filter_by(is_active=True).all()
    result = []
    for reward in rewards:
        result.append({
            'id': reward.id,
            'title': reward.title,
            'points_cost': reward.points_cost,
            'can_afford': reward.points_cost <= balance
        })
    return jsonify({'balance': balance, 'rewards': result})


@app.route('/api/redeem', methods=['POST'])
@jwt_required()
def redeem():
    data = request.get_json() or {}
    reward_id = data.get('reward_id')
    if not reward_id:
        return jsonify({"error": "reward_id is required"}), 400

    user_id = get_jwt_identity()
    balance = db.session.query(func.sum(PointTxn.delta)).filter_by(user_id=user_id).scalar() or 0
    reward = Reward.query.filter_by(id=reward_id, is_active=True).first()
    if not reward:
        return jsonify({"error": "Reward not found or inactive"}), 404

    if balance < reward.points_cost:
        return jsonify({"error": "Insufficient points"}), 400

    code = str(uuid.uuid4())
    redemption = Redemption(user_id=user_id, reward_id=reward_id, code=code)
    txn = PointTxn(user_id=user_id, delta=-reward.points_cost, reason=f"Redeemed: {reward.title}")
    db.session.add(redemption)
    db.session.add(txn)
    db.session.commit()
    return jsonify({"code": code, "reward_title": reward.title}), 201


if __name__ == "__main__":
    app.run(debug=True)
