from dotenv import load_dotenv
load_dotenv()

import os
import uuid
from pathlib import Path

from flask import Flask, jsonify, request
from flask_jwt_extended import create_access_token
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import and_, func, or_
from google import genai
from google.genai import types

from extensions import db, jwt

from models import Challenge, Enrollment, PointTxn, Reward, Redemption, User
from flask_jwt_extended import jwt_required, get_jwt_identity
from flask_cors import CORS

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials as firebase_credentials


_BACKEND_DIR = Path(__file__).resolve().parent
_INSTANCE_DIR = _BACKEND_DIR / "instance"
_INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
# Stable on-disk SQLite (same file no matter which cwd you start Flask from).
_DEFAULT_SQLITE_URI = "sqlite:///" + (_INSTANCE_DIR / "kashe_dev.db").resolve().as_posix()

app = Flask(__name__)

CORS(
    app,
    origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
)

app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", _DEFAULT_SQLITE_URI
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


def _ensure_firebase_admin():
    if firebase_admin._apps:
        return True
    cred_path = (
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        or os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
    )
    path = Path(cred_path).expanduser() if cred_path else None
    if not path or not path.is_file():
        default_json = _BACKEND_DIR / "serviceAccount.json"
        if default_json.is_file():
            path = default_json
        else:
            return False
    firebase_admin.initialize_app(firebase_credentials.Certificate(str(path)))
    return True


@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "ok", "app": "Kashé API"})


@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password")

    if not name or not email or not password:
        return jsonify({"error": "Name, email, and password are required"}), 400

    existing = models.User.query.filter(
        func.lower(models.User.email) == email
    ).first()
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
    # Accept "email" or "username" — same field for whatever the user typed (email or display name).
    identifier = (data.get("email") or data.get("username") or "").strip()
    password = data.get("password")

    if not identifier or not password:
        return jsonify({"error": "Email and password are required"}), 400

    user = models.User.query.filter(
        func.lower(models.User.email) == func.lower(identifier)
    ).first()
    if not user:
        name_matches = models.User.query.filter(
            func.lower(models.User.name) == func.lower(identifier)
        ).all()
        if len(name_matches) == 1:
            user = name_matches[0]

    if not user:
        return jsonify({"error": "No account found for that email or name."}), 401

    if not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Incorrect password."}), 401

    token = create_access_token(identity=str(user.id))
    return jsonify({
        "token": token,
        "name": user.name,
        "email": user.email,
        "created_at": user.created_at.isoformat()
    }), 200


@app.route("/api/auth/google", methods=["POST"])
def auth_google():
    firebase_id_token = (request.get_json() or {}).get("token") or ""
    if not firebase_id_token:
        return jsonify({"error": "token is required"}), 400

    if not _ensure_firebase_admin():
        return jsonify(
            {
                "error": "Google sign-in is not configured. Place serviceAccount.json in the "
                "backend folder, or set GOOGLE_APPLICATION_CREDENTIALS / FIREBASE_SERVICE_ACCOUNT_PATH "
                "to your Firebase service account JSON file.",
            }
        ), 503

    try:
        decoded = firebase_auth.verify_id_token(firebase_id_token)
    except Exception:
        return jsonify({"error": "Invalid or expired Google token."}), 401

    email = (decoded.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "Google account has no email on file."}), 400

    display_name = (decoded.get("name") or "").strip()
    if not display_name:
        local = email.split("@")[0]
        display_name = local.replace(".", " ").title() if local else "Member"

    user = models.User.query.filter(func.lower(models.User.email) == email).first()
    if not user:
        random_pw = uuid.uuid4().hex
        user = models.User(
            name=display_name,
            email=email,
            password_hash=generate_password_hash(random_pw),
        )
        db.session.add(user)
        db.session.commit()
    token = create_access_token(identity=str(user.id))
    return jsonify({
        "token": token,
        "name": user.name,
        "email": user.email,
        "created_at": user.created_at.isoformat(),
    }), 200


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


@app.route('/api/challenges/<int:challenge_id>', methods=['GET'])
@jwt_required()
def get_challenge_detail(challenge_id):
    challenge = Challenge.query.get(challenge_id)
    if not challenge:
        return jsonify({'error': 'Challenge not found'}), 404

    return jsonify({
        'id': challenge.id,
        'title': challenge.title,
        'required_classes': challenge.required_classes,
        'points_reward': challenge.points_reward,
        'deadline': str(challenge.deadline) if challenge.deadline else None,
        'is_active': challenge.is_active
    })


@app.route('/api/enrollments', methods=['GET'])
@jwt_required()
def get_enrollments():
    user_id = get_jwt_identity()
    enrollments = Enrollment.query.filter_by(user_id=user_id).all()
    result = []
    for enrollment in enrollments:
        challenge = Challenge.query.get(enrollment.challenge_id)
        if not challenge:
            continue
        result.append({
            'id': enrollment.id,
            'challenge_id': challenge.id,
            'title': challenge.title,
            'classes_completed': enrollment.classes_completed,
            'required_classes': challenge.required_classes,
            'points_reward': challenge.points_reward,
            'status': enrollment.status
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


@app.route("/api/webhook/mindbody", methods=["POST"])
def mindbody_webhook():
    """Simulated MindBody attendance webhook (no JWT)."""
    data = request.get_json() or {}
    mindbody_email = (data.get("mindbody_email") or "").strip().lower()
    class_name = (data.get("class_name") or "").strip()
    _studio_name = (data.get("studio_name") or "").strip()
    _attended_at = data.get("attended_at")

    if not mindbody_email or not class_name:
        return jsonify(
            {
                "success": False,
                "message": "mindbody_email and class_name are required",
            }
        ), 400

    user = models.User.query.filter(
        or_(
            func.lower(models.User.email) == mindbody_email,
            and_(
                models.User.mindbody_email.isnot(None),
                func.lower(models.User.mindbody_email) == mindbody_email,
            ),
        )
    ).first()
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 200

    # Partial match: challenge title contains class_name (case insensitive)
    pattern = f"%{class_name.replace('%', '').replace('_', '')}%"
    enrollment = (
        Enrollment.query.join(Challenge, Enrollment.challenge_id == Challenge.id)
        .filter(
            Enrollment.user_id == user.id,
            Enrollment.status == "active",
            Challenge.title.ilike(pattern),
        )
        .first()
    )
    if not enrollment:
        return jsonify(
            {
                "success": False,
                "message": "No matching challenge enrollment found",
            }
        ), 200

    challenge = Challenge.query.get(enrollment.challenge_id)
    if not challenge:
        return jsonify(
            {"success": False, "message": "No matching challenge enrollment found"}
        ), 200

    enrollment.classes_completed += 1
    message = f"Logged attendance for {challenge.title}."
    if enrollment.classes_completed >= challenge.required_classes:
        enrollment.status = "completed"
        txn = PointTxn(
            user_id=user.id,
            delta=challenge.points_reward,
            reason=f"Completed: {challenge.title}",
        )
        db.session.add(txn)
        message = f"Completed challenge: {challenge.title}."

    db.session.commit()
    return jsonify(
        {
            "success": True,
            "message": message,
            "classes_completed": enrollment.classes_completed,
        }
    ), 200


@app.route("/api/webhook/mindbody/status", methods=["GET"])
@jwt_required()
def mindbody_webhook_status():
    """Recent point transactions (e.g. after MindBody webhook simulation)."""
    rows = (
        PointTxn.query.order_by(PointTxn.created_at.desc()).limit(10).all()
    )
    return jsonify(
        {
            "recent_point_txns": [
                {
                    "reason": t.reason,
                    "delta": t.delta,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in rows
            ]
        }
    )


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


@app.route('/api/profile/stats', methods=['GET'])
@jwt_required()
def get_profile_stats():
    user_id = get_jwt_identity()
    challenges_completed = Enrollment.query.filter_by(user_id=user_id, status='completed').count()
    rewards_redeemed = Redemption.query.filter_by(user_id=user_id).count()
    return jsonify({
        "challenges_completed": challenges_completed,
        "rewards_redeemed": rewards_redeemed
    })


@app.route('/api/point_txns/lifetime', methods=['GET'])
@jwt_required()
def get_lifetime_points():
    user_id = get_jwt_identity()
    lifetime_points = db.session.query(func.sum(PointTxn.delta)).filter(PointTxn.user_id == user_id, PointTxn.delta > 0).scalar() or 0
    return jsonify({"lifetime_points": lifetime_points})


# --- Gemini chat tools (read + action). DB access runs inside app.app_context(). ---

CHAT_SYSTEM_INSTRUCTION = """You are an action-oriented Kashé fitness coach and assistant.
Kashé is a fitness loyalty app where users earn points by completing
class challenges and redeem them for rewards.

CRITICAL RULES:
- When a user confirms they want to do something, IMMEDIATELY call
  the appropriate tool. Do not describe what you will do - just do it.
- When user says 'yes', 'yup', 'sure', 'ok', 'do it', or any
  confirmation - call the action tool right away.
- Never say 'I'll enroll you' without actually calling enroll_in_challenge.
- Never say 'I'll log a class' without actually calling log_class_for_challenge.
- Never say 'I'll redeem' without actually calling redeem_reward_for_user.
- After calling a tool, report the result to the user.

You have tools to look up data AND take real actions.
For logging a class, just do it directly without asking.
For enrolling and redeeming, confirm once then immediately act.
Be encouraging, brief, and action-oriented.

Never use markdown formatting like **bold** or *bullets*
in your responses. Use plain text only.

The authenticated user's ID is: {authenticated_user_id}"""


def get_user_balance(user_id: str) -> dict:
    """Get the user's current point balance.

    Args:
        user_id: Authenticated user's id (string from JWT).

    Returns:
        dict with key ``balance`` (int).
    """
    with app.app_context():
        balance = (
            db.session.query(func.sum(PointTxn.delta)).filter_by(user_id=user_id).scalar()
            or 0
        )
        return {"balance": balance}


def get_user_challenges(user_id: str) -> dict:
    """Get all of the user's enrollments (active and completed) and their progress.

    Args:
        user_id: Authenticated user's id (string from JWT).

    Returns:
        dict with key ``challenges``: list of dicts with title, classes_completed,
        required_classes, points_reward, status.
    """
    with app.app_context():
        enrollments = Enrollment.query.filter_by(user_id=user_id).all()
        challenges = []
        for enrollment in enrollments:
            challenge = Challenge.query.get(enrollment.challenge_id)
            if challenge:
                challenges.append({
                    "title": challenge.title,
                    "classes_completed": enrollment.classes_completed,
                    "required_classes": challenge.required_classes,
                    "points_reward": challenge.points_reward,
                    "status": enrollment.status,
                })
        return {"challenges": challenges}


def list_available_challenges(user_id: str) -> dict:
    """List active challenges the user is not enrolled in yet.

    Args:
        user_id: Authenticated user's id (string from JWT).

    Returns:
        dict with key ``challenges``: list of dicts with id, title, required_classes, points_reward.
    """
    with app.app_context():
        enrolled_ids = [
            row[0]
            for row in db.session.query(Enrollment.challenge_id)
            .filter_by(user_id=user_id)
            .distinct()
            .all()
        ]
        q = Challenge.query.filter_by(is_active=True)
        if enrolled_ids:
            q = q.filter(~Challenge.id.in_(enrolled_ids))
        rows = q.all()
        return {
            "challenges": [
                {
                    "id": c.id,
                    "title": c.title,
                    "required_classes": c.required_classes,
                    "points_reward": c.points_reward,
                }
                for c in rows
            ]
        }


def enroll_in_challenge(user_id: str, challenge_title: str) -> dict:
    """Enroll the user in an active challenge.

    Args:
        user_id: Authenticated user's id (string from JWT).
        challenge_title: Challenge title (case-insensitive match).

    Returns:
        On success: ``{"success": True, "message": "Enrolled in [title]!"}``.
        On failure: ``{"success": False, "message": "..."}``.
    """
    with app.app_context():
        title = (challenge_title or "").strip()
        if not title:
            return {"success": False, "message": "Challenge not found or inactive."}

        challenge = Challenge.query.filter(
            Challenge.is_active.is_(True),
            Challenge.title.ilike(title),
        ).first()
        if not challenge:
            return {"success": False, "message": "Challenge not found or inactive."}

        existing = Enrollment.query.filter_by(
            user_id=user_id, challenge_id=challenge.id
        ).first()
        if existing:
            return {"success": False, "message": "Already enrolled in this challenge."}

        enrollment = Enrollment(
            user_id=user_id,
            challenge_id=challenge.id,
            classes_completed=0,
            status="active",
        )
        db.session.add(enrollment)
        db.session.commit()
        return {
            "success": True,
            "message": f"Enrolled in {challenge.title}!",
        }


def log_class_for_challenge(user_id: str, challenge_title: str) -> dict:
    """Log one completed class toward the user's enrollment for a challenge.

    Args:
        user_id: Authenticated user's id (string from JWT).
        challenge_title: Challenge title (case-insensitive match).

    Returns:
        On success: ``{"success": True, "classes_completed": int, "completed": bool, "points_earned": int}``.
        On failure: ``{"success": False, "message": "..."}``.
    """
    with app.app_context():
        title = (challenge_title or "").strip()
        if not title:
            return {"success": False, "message": "Challenge not found"}

        challenge = Challenge.query.filter(Challenge.title.ilike(title)).first()
        if not challenge:
            return {"success": False, "message": "Challenge not found"}

        enrollment = Enrollment.query.filter_by(
            user_id=user_id, challenge_id=challenge.id
        ).first()
        if not enrollment:
            return {"success": False, "message": "Not enrolled in this challenge."}

        if enrollment.status == "completed":
            return {"success": False, "message": "Challenge already completed."}

        enrollment.classes_completed += 1
        completed = False
        points_earned = 0
        if enrollment.classes_completed >= challenge.required_classes:
            enrollment.status = "completed"
            completed = True
            points_earned = challenge.points_reward
            txn = PointTxn(
                user_id=user_id,
                delta=points_earned,
                reason=f"Completed: {challenge.title}",
            )
            db.session.add(txn)

        db.session.commit()
        return {
            "success": True,
            "classes_completed": enrollment.classes_completed,
            "completed": completed,
            "points_earned": points_earned,
        }


def get_available_rewards(user_id: str) -> dict:
    """List active rewards the user can afford with their current balance.

    Args:
        user_id: Authenticated user's id (string from JWT).

    Returns:
        dict with key ``rewards``: list of dicts with id, title, points_cost.
    """
    with app.app_context():
        balance = (
            db.session.query(func.sum(PointTxn.delta)).filter_by(user_id=user_id).scalar()
            or 0
        )
        rewards = Reward.query.filter_by(is_active=True).all()
        affordable = [
            {
                "id": r.id,
                "title": r.title,
                "points_cost": r.points_cost,
            }
            for r in rewards
            if r.points_cost <= balance
        ]
        return {"rewards": affordable}


def redeem_reward_for_user(user_id: str, reward_title: str) -> dict:
    """Redeem a reward: creates a redemption record and deducts points.

    Args:
        user_id: Authenticated user's id (string from JWT).
        reward_title: Reward title (case-insensitive match).

    Returns:
        On success: ``{"success": True, "code": str, "reward_title": str}``.
        On failure: ``{"success": False, "message": "..."}``.
    """
    with app.app_context():
        balance = (
            db.session.query(func.sum(PointTxn.delta)).filter_by(user_id=user_id).scalar()
            or 0
        )
        title = (reward_title or "").strip()
        if not title:
            return {"success": False, "message": "Reward not found or inactive."}

        reward = Reward.query.filter(
            Reward.is_active.is_(True),
            Reward.title.ilike(title),
        ).first()
        if not reward:
            return {"success": False, "message": "Reward not found or inactive."}

        if balance < reward.points_cost:
            return {"success": False, "message": "Insufficient points."}

        code = str(uuid.uuid4())
        redemption = Redemption(user_id=user_id, reward_id=reward.id, code=code)
        txn = PointTxn(
            user_id=user_id,
            delta=-reward.points_cost,
            reason=f"Redeemed: {reward.title}",
        )
        db.session.add(redemption)
        db.session.add(txn)
        db.session.commit()
        return {"success": True, "code": code, "reward_title": reward.title}


GEMINI_CHAT_TOOLS = [
    get_user_balance,
    get_user_challenges,
    list_available_challenges,
    enroll_in_challenge,
    log_class_for_challenge,
    get_available_rewards,
    redeem_reward_for_user,
]


def _chat_history_to_contents(history, latest_user_message: str):
    """Build Gemini ``contents`` from client history plus the new user turn."""
    contents = []
    if isinstance(history, list):
        for item in history:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            text = item.get("text")
            if role not in ("user", "model") or text is None:
                continue
            text = str(text).strip()
            if not text:
                continue
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part(text=text)],
                )
            )
    text = str(latest_user_message).strip()
    if text:
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part(text=text)],
            )
        )
    return contents


@app.route('/api/chat', methods=['POST'])
@jwt_required()
def chat():
    """Chat endpoint with Gemini AI using automatic tool calling (read + actions)."""
    data = request.get_json() or {}
    message = data.get("message")
    history = data.get("history")

    if not message or not str(message).strip():
        return jsonify({"error": "message is required"}), 400

    if history is not None and not isinstance(history, list):
        return jsonify({"error": "history must be an array when provided"}), 400

    contents = _chat_history_to_contents(history or [], message)
    if not contents:
        return jsonify({"error": "message is required"}), 400

    user_id = get_jwt_identity()
    system_instruction = CHAT_SYSTEM_INSTRUCTION.format(
        authenticated_user_id=user_id
    )

    try:
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=GEMINI_CHAT_TOOLS,
            ),
        )

        return jsonify({"reply": response.text}), 200

    except Exception as err:
        print(f"Chat error: {str(err)}")  # Debug logging
        return jsonify({"error": f"Chat service error: {str(err)}"}), 500


if __name__ == "__main__":
    app.run(debug=True)
