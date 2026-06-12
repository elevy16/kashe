from dotenv import load_dotenv
load_dotenv()

import json
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, Response, jsonify, request, stream_with_context
from flask_jwt_extended import create_access_token
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import and_, func, or_
from google import genai
from google.genai import types

from extensions import db, jwt, socketio

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

cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]

CORS(app, origins=cors_origins)

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
socketio.init_app(app, cors_allowed_origins=cors_origins)

# Import models after extensions are initialized to avoid circular imports
import models  # noqa: F401

# Ensure tables are created on startup
with app.app_context():
    db.create_all()


@socketio.on("connect")
def handle_connect():
    print("Client connected")


def _emit_points_updated(
    user_id,
    *,
    classes_completed,
    challenge_title,
    completed,
    points_earned,
):
    """Broadcast balance + check-in progress after DB commit (all clients; filter client-side)."""
    uid = str(user_id)
    new_balance = (
        db.session.query(func.sum(PointTxn.delta)).filter_by(user_id=uid).scalar() or 0
    )
    print(f"Emitting points_updated for user {user_id}, balance {new_balance}")
    socketio.emit(
        "points_updated",
        {
            "user_id": uid,
            "new_balance": int(new_balance),
            "classes_completed": int(classes_completed),
            "challenge_title": challenge_title or "",
            "completed": bool(completed),
            "points_earned": int(points_earned or 0),
        },
        to=None,
    )


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
    _emit_points_updated(
        user_id,
        classes_completed=enrollment.classes_completed,
        challenge_title=challenge.title if challenge else "",
        completed=completed,
        points_earned=points_earned,
    )
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

GREETING_SYSTEM_INSTRUCTION = (
    "Generate a short personalized greeting from Kai, a friendly Kashé fitness coach. "
    "Start with 'Hi [name], I'm Kai!' using the user's first name from the data. "
    "Then mention one specific thing about their progress (a challenge close to done, "
    "recent points, or an active streak). Keep it to 2 sentences max. No markdown. "
    "Be warm, motivating, and actionable."
)

_WEEKDAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
# Spread workouts across the week (at least 2 rest days; max 5 workout days).
_WEEKLY_PLAN_DAY_INDICES = [0, 2, 4, 1, 3]


def _build_activity_summary(user_id: str) -> dict:
    """Build activity summary dict for chat context, tools, and greetings (expects app context)."""
    uid = int(user_id)
    balance = (
        db.session.query(func.sum(PointTxn.delta)).filter_by(user_id=uid).scalar() or 0
    )

    enrollments_out = []
    for enrollment in Enrollment.query.filter_by(user_id=uid).all():
        challenge = db.session.get(Challenge, enrollment.challenge_id)
        if not challenge:
            continue
        enrollments_out.append(
            {
                "title": challenge.title,
                "classes_completed": enrollment.classes_completed,
                "required_classes": challenge.required_classes,
                "points_reward": challenge.points_reward,
                "status": enrollment.status,
            }
        )

    recent_txns = (
        PointTxn.query.filter_by(user_id=uid)
        .order_by(PointTxn.created_at.desc())
        .limit(5)
        .all()
    )
    recent_point_txns = [
        {
            "reason": t.reason,
            "delta": t.delta,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in recent_txns
    ]

    seven_ago = datetime.utcnow() - timedelta(days=7)

    challenges_completed_last_7_days = []
    for txn in (
        PointTxn.query.filter(
            PointTxn.user_id == uid,
            PointTxn.delta > 0,
            PointTxn.created_at >= seven_ago,
            PointTxn.reason.isnot(None),
            PointTxn.reason.like("Completed:%"),
        )
        .order_by(PointTxn.created_at.desc())
        .all()
    ):
        title = (txn.reason or "").replace("Completed:", "").strip()
        challenges_completed_last_7_days.append(
            {
                "title": title,
                "points_earned": txn.delta,
                "completed_at": txn.created_at.isoformat() if txn.created_at else None,
            }
        )

    rewards_redeemed_last_7_days = []
    for redemption in (
        Redemption.query.filter(
            Redemption.user_id == uid,
            Redemption.redeemed_at >= seven_ago,
        )
        .order_by(Redemption.redeemed_at.desc())
        .all()
    ):
        reward = db.session.get(Reward, redemption.reward_id)
        rewards_redeemed_last_7_days.append(
            {
                "reward_title": reward.title if reward else "",
                "redeemed_at": redemption.redeemed_at.isoformat()
                if redemption.redeemed_at
                else None,
            }
        )

    return {
        "balance": int(balance),
        "enrollments": enrollments_out,
        "recent_point_txns": recent_point_txns,
        "challenges_completed_last_7_days": challenges_completed_last_7_days,
        "rewards_redeemed_last_7_days": rewards_redeemed_last_7_days,
    }


CHAT_SYSTEM_INSTRUCTION = """You are Kai, an action-oriented Kashé fitness coach and assistant.
Kashé is a fitness loyalty app where users earn points by completing
class challenges and redeem them for rewards.

On the very first message of a conversation only (no prior assistant replies in history),
introduce yourself once as: "Hi! I'm Kai, your Kashé fitness coach" then answer their question.
Do not repeat the full introduction on later messages.

You know boutique fitness: studios like SoulCycle, Club Pilates, CorePower Yoga,
Pure Barre, Barry's, and similar venues, plus common class types including HIIT,
Pilates, Barre, Yoga, Strength, and cardio-forward formats.

You understand recovery and rest days matter as much as workout days. Consistency beats
intensity — encourage sustainable weekly habits, not burnout.

When the user asks "plan my week", "help me plan", or "what should I do this week":
call suggest_weekly_plan and present the result as a clear day-by-day schedule with reasons.

When the user asks "am I on pace", "will I finish in time", or similar deadline questions:
call analyze_weekly_pace and give specific feedback with real numbers and challenge names.

When the user seems discouraged or asks for motivation (e.g. "motivate me", "I'm struggling"):
call get_motivational_context and use the stats to encourage them with real numbers.

When the user asks what they should do next, or wants a recommendation, use their
current enrollments and progress (from your tools) to suggest they prioritize the
challenge they are closest to completing first, then others.

Always be specific — use real numbers, real challenge names, and real deadlines from tools.
Never invent progress or dates.

After you successfully log a class for them, check if they are now within one or
two classes of finishing that challenge and mention it when relevant.

After they complete a challenge, mention which rewards they can now afford. Kashé
rewards include real partner brands such as Pressed Juicery, Lululemon, SoulCycle,
Alo Yoga, Spotify Premium, and Sakara Life when naming options.

After they redeem a reward, congratulate them and suggest a challenge to work
toward next.

Never ask for numeric IDs for challenges or rewards. Always use names.

When matching challenge names from user messages, always use case-insensitive
matching. If the user types 'pilates powerhouse' or 'Pilates Powerhouse' or
'PILATES POWERHOUSE', treat them all the same. Never fail to recognize a challenge
name just because of capitalization.

VOICE AND FORMATTING (Kai — premium wellness brand):
- Clean, minimal, elegant. Generous line breaks — one idea per line.
- Short sentences. Direct. Never generic or cheerleader-ish.
- Tone: knowledgeable personal trainer who respects the user's intelligence. Warm but efficient.
- Use minimal geometric unicode accents very sparingly for structure only: ◆ ◇ · — › ○ ●
  Never standard emojis. Never clipart energy.
- Weekly plans and pace checks should read like a formatted card, not a paragraph.
  Example structure:
  ◆ Your week
  Monday · Pilates Powerhouse
  › Two classes left to stay on pace
- Never use markdown bold (**), asterisks, or hyphen bullet lists (-).
- End with one forward-looking sentence (› ...). Never backward-looking praise.

CRITICAL RULES:
- When a user confirms they want to do something, IMMEDIATELY call
  the appropriate tool. Do not describe what you will do - just do it.
- When user says 'yes', 'yup', 'sure', 'ok', 'do it', or any
  confirmation - call the action tool right away.
- Never say 'I'll enroll you' without actually calling enroll_in_challenge.
- Never say 'I'll log a class' without actually calling log_class_for_challenge.
- Never say 'I'll redeem' without actually calling redeem_reward_for_user.
- After calling a tool, report the result to the user.
- Use get_user_activity_summary when you need a full snapshot of recent activity,
  balance, enrollments, point history, and weekly completions and redemptions.

You have tools to look up data AND take real actions.
For logging a class, just do it directly without asking.
Phrasings like "log a class for pilates powerhouse", "Log a class for Pilates Powerhouse",
"record a class toward barre basics", or "please log my class for cardio crush" all mean
the same intent: call log_class_for_challenge immediately with the challenge name the user
gave. Do this for any capitalization or minor wording variation. The tool matches
challenge names case-insensitively, so never skip calling it because the user used lowercase.

For enrolling and redeeming, confirm once then immediately act.

Never reply with apologies like "sorry, I didn't understand". If unsure, steer the
user toward Kashé: logging classes toward challenges, enrolling, checking balance,
or redeeming rewards (Pressed Juicery, Lululemon, SoulCycle, Alo Yoga, Sakara Life, Spotify).

When the user confirms yes after seeing an offer to enroll before logging a class,
they want you to enroll them and log the same class immediately.

If a tool explains that the challenge or reward wasn't found but lists alternatives,
reuse that detail verbatim for the user.

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


def get_user_activity_summary(user_id: str) -> dict:
    """Summarize recent user activity: enrollments, recent PointTxns, balance,
    challenges completed in the last 7 days, rewards redeemed in the last 7 days.

    Args:
        user_id: Authenticated user's id (string from JWT).

    Returns:
        dict with keys: balance, enrollments, recent_point_txns,
        challenges_completed_last_7_days, rewards_redeemed_last_7_days.
    """
    with app.app_context():
        return _build_activity_summary(user_id)


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


def _alnum_compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _spaced_normalized(text: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        re.sub(r"[^a-z0-9]+", " ", (text or "").lower()),
    ).strip()


def _title_tokens(title: str) -> list:
    return re.findall(r"[a-z0-9]+", (title or "").lower())


def _rank_challenges_by_fragment(fragment: str, challenges: list) -> list:
    """Return ``[(challenge, score), ...]`` best first.

    Score counts title words (len>=2) found as substrings of the user's compact
    string (handles fused typos like flowjourney). Exact compact / spaced matches win.
    """
    fragment = (fragment or "").strip()
    if not fragment:
        return []

    user_c = _alnum_compact(fragment)
    user_s = _spaced_normalized(fragment)
    ranked = []
    for ch in challenges:
        words = _title_tokens(ch.title)
        if not words:
            continue
        ch_c = "".join(words)
        ch_s = _spaced_normalized(ch.title)
        exact = user_c == ch_c or user_s == ch_s
        score = sum(1 for w in words if len(w) >= 2 and w in user_c)
        if exact:
            score = max(score, len(words) + 1)
        ranked.append((ch, score))

    ranked.sort(key=lambda t: (-(t[1]), len(t[0].title)))
    return ranked


def resolve_challenge_for_enroll(fragment: str):
    """Best active Challenge for enroll intent, or None."""
    fragment = (fragment or "").strip()
    if not fragment:
        return None
    rows = Challenge.query.filter(Challenge.is_active.is_(True)).all()
    if not rows:
        return None
    ranked = _rank_challenges_by_fragment(fragment, rows)
    if not ranked:
        return None
    best_score = ranked[0][1]
    if best_score == 0:
        return None
    return ranked[0][0]


def resolve_challenge_for_log(user_id: str, fragment: str):
    """Resolve challenge for logging: prefers enrollments user has."""
    fragment = (fragment or "").strip()
    if not fragment:
        return None, []
    enrolled_ids = (
        db.session.query(Enrollment.challenge_id)
        .filter_by(user_id=int(user_id))
        .distinct()
        .all()
    )
    enrolled_set = {r[0] for r in enrolled_ids}

    pool = Challenge.query.all()
    ranked_plain = _rank_challenges_by_fragment(fragment, pool)
    enrolled_first = []
    for row in ranked_plain:
        ch = row[0]
        score = row[1]
        if ch.id in enrolled_set:
            enrolled_first.append((ch, score))
    enrolled_first.sort(key=lambda t: -t[1])
    ranked_plain_sorted = sorted(ranked_plain, key=lambda t: (-t[1], len(t[0].title)))

    if enrolled_first and enrolled_first[0][1] > 0:
        return enrolled_first[0][0], ranked_plain_sorted
    if ranked_plain_sorted and ranked_plain_sorted[0][1] > 0:
        return ranked_plain_sorted[0][0], ranked_plain_sorted
    return None, ranked_plain_sorted


def resolve_reward_by_fragment(fragment: str):
    """Best active Reward match for redeem intent."""
    fragment = (fragment or "").strip()
    if not fragment:
        return None
    rows = Reward.query.filter(Reward.is_active.is_(True)).all()
    if not rows:
        return None
    user_c = _alnum_compact(fragment)
    user_s = _spaced_normalized(fragment)
    best = None
    best_score = -1
    for r in rows:
        words = _title_tokens(r.title)
        if not words:
            continue
        r_c = "".join(words)
        r_s = _spaced_normalized(r.title)
        exact = user_c == r_c or user_s == r_s
        score = sum(1 for w in words if len(w) >= 2 and w in user_c)
        if exact:
            score = max(score, len(words) + 1)
        if score > best_score:
            best_score = score
            best = r
    if best_score <= 0:
        return None
    return best


def _format_available_challenges_for_user(user_id: str) -> str:
    data = list_available_challenges(user_id)
    chals = data.get("challenges") or []
    if not chals:
        return "You are already enrolled in every challenge we have right now. Log classes toward your active challenges to earn points, or ask me how close you are to finishing one."
    lines = ", ".join(c["title"] for c in chals[:12])
    more = f" (and {len(chals) - 12} more)" if len(chals) > 12 else ""
    return f"Here are challenges you can still join: {lines}{more}."


def _fastest_points_path(user_id: str, points_needed: int) -> str:
    """Coach-style hint: gap + best challenge completion to cite."""
    uid = int(user_id)
    gap = max(int(points_needed), 1)
    first = (
        f"You need {gap} more point{'s' if gap != 1 else ''}"
        if gap
        else "You could use more points toward that reward."
    )

    feasible = []
    for e in Enrollment.query.filter_by(user_id=uid, status="active").all():
        ch = db.session.get(Challenge, e.challenge_id)
        if not ch:
            continue
        rem = max(ch.required_classes - e.classes_completed, 0)
        if rem <= 0:
            continue
        pts = ch.points_reward
        if pts >= gap:
            feasible.append((rem, pts, ch.title))

    feasible.sort(key=lambda t: (t[0], -t[1]))
    if feasible:
        rem, pts, title = feasible[0]
        return f"{first}. Completing {title} would earn you {pts} points{f' — only {rem} class(es) away' if rem else ''}!"

    best = []
    for e in Enrollment.query.filter_by(user_id=uid, status="active").all():
        ch = db.session.get(Challenge, e.challenge_id)
        if not ch:
            continue
        rem = max(ch.required_classes - e.classes_completed, 0)
        if rem <= 0:
            continue
        best.append((ch.points_reward / max(rem, 1), rem, ch.points_reward, ch.title))
    best.sort(key=lambda t: (-t[0], t[1]))
    if best:
        _, rem, pts, title = best[0]
        return f"{first}. Working toward finishing {title} earns {pts} points with {rem} class(es) to go."

    avail = Challenge.query.filter(Challenge.is_active.is_(True)).count()
    if avail:
        return f"{first}. Enrolling in an open challenge and finishing it is your fastest route to stacking points."

    return f"{first}. Enroll in any open challenge — each completion unlocks Kashé rewards."


def enroll_in_challenge(user_id: str, challenge_title: str) -> dict:
    """Enroll the user in an active challenge (fuzzy title match).

    Args:
        user_id: Authenticated user's id (string from JWT).
        challenge_title: Challenge title from the user; normalized and fuzzy-matched.

    Returns:
        On success: ``{"success": True, "message": "..."}``.
        On failure: ``{"success": False, "message": "...", ...}``.
    """
    with app.app_context():
        fragment = (challenge_title or "").strip()
        if not fragment:
            return {
                "success": False,
                "message": "Tell me which challenge you want to join by name.",
            }

        challenge = resolve_challenge_for_enroll(fragment)
        if not challenge:
            hint = _format_available_challenges_for_user(user_id)
            return {
                "success": False,
                "message": f"I could not find a challenge called {fragment!r}. {hint}",
            }

        existing = Enrollment.query.filter_by(
            user_id=user_id, challenge_id=challenge.id
        ).first()
        if existing:
            return {
                "success": False,
                "message": f"You are already enrolled in {challenge.title}.",
            }

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
            "challenge_title": challenge.title,
        }


def log_class_for_challenge(user_id: str, challenge_title: str) -> dict:
    """Log one completed class toward the user's enrollment for a challenge.

    Args:
        user_id: Authenticated user's id (string from JWT).
        challenge_title: Challenge title fragment; fuzzy-matched to challenges.

    Returns:
        On success: ``{"success": True, ...}``.
        On failure: includes ``reason`` when machine-readable (``not_enrolled``,
        ``not_found``, ``already_completed``).
    """
    with app.app_context():
        fragment = (challenge_title or "").strip()
        if not fragment:
            return {"success": False, "message": "Challenge not found", "reason": "not_found"}

        challenge, _alts = resolve_challenge_for_log(user_id, fragment)
        if not challenge:
            return {"success": False, "message": "Challenge not found", "reason": "not_found"}

        enrollment = Enrollment.query.filter_by(
            user_id=user_id, challenge_id=challenge.id
        ).first()
        if not enrollment:
            return {
                "success": False,
                "message": f"Not enrolled in {challenge.title}.",
                "reason": "not_enrolled",
                "challenge_title": challenge.title,
            }

        if enrollment.status == "completed":
            return {
                "success": False,
                "message": f"You already completed {challenge.title}.",
                "reason": "already_completed",
                "challenge_title": challenge.title,
            }

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
        _emit_points_updated(
            user_id,
            classes_completed=enrollment.classes_completed,
            challenge_title=challenge.title,
            completed=completed,
            points_earned=points_earned,
        )
        return {
            "success": True,
            "classes_completed": enrollment.classes_completed,
            "completed": completed,
            "points_earned": points_earned,
            "challenge_title": challenge.title,
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
        reward_title: Reward fragment; fuzzy matched to titles.

    Returns:
        On success: ``{"success": True, "code": str, "reward_title": str}``.
        On failure: ``{"success": False, "message": "...", ...}`` may include ``reason``.
    """
    with app.app_context():
        balance = (
            db.session.query(func.sum(PointTxn.delta)).filter_by(user_id=user_id).scalar()
            or 0
        )
        fragment = (reward_title or "").strip()
        if not fragment:
            return {"success": False, "message": "Tell me which reward you want."}

        reward = resolve_reward_by_fragment(fragment)
        if not reward:
            rows = Reward.query.filter_by(is_active=True).all()
            names = ", ".join(r.title for r in rows[:10])
            suffix = " … and more!" if len(rows) > 10 else ""
            return {
                "success": False,
                "reason": "reward_not_found",
                "message": (
                    f"I could not match a reward called {fragment!r}. Rewards in Kashé "
                    f"right now include: {names}{suffix}."
                ),
            }

        balance = int(balance)
        if balance < reward.points_cost:
            need = reward.points_cost - balance
            hint = _fastest_points_path(user_id, need)
            msg = hint
            return {
                "success": False,
                "reason": "insufficient_points",
                "reward_title": reward.title,
                "points_needed": need,
                "reward_cost": reward.points_cost,
                "balance": balance,
                "message": msg,
            }

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


def _build_pace_analysis(user_id: str) -> list:
    """Pace rows for active enrollments (expects Flask app context)."""
    uid = int(user_id)
    now = datetime.utcnow()
    rows = []

    for enrollment in Enrollment.query.filter_by(user_id=uid, status="active").all():
        challenge = db.session.get(Challenge, enrollment.challenge_id)
        if not challenge:
            continue

        required = challenge.required_classes or 0
        completed = enrollment.classes_completed or 0
        remaining = max(required - completed, 0)
        if remaining <= 0:
            continue

        if not challenge.deadline:
            rows.append(
                {
                    "challenge_title": challenge.title,
                    "classes_remaining": remaining,
                    "days_until_deadline": None,
                    "classes_per_week_needed": None,
                    "status": "no_deadline",
                }
            )
            continue

        delta = challenge.deadline - now
        days_until = max(int(delta.total_seconds() // 86400), 0)
        weeks_left = max(days_until / 7.0, 0.01)
        cpw = round(remaining / weeks_left, 1)

        if days_until == 0 and remaining > 0:
            status = "behind"
        else:
            start = enrollment.created_at or now
            total_span = (challenge.deadline - start).total_seconds()
            if total_span <= 0:
                status = "on_pace"
            else:
                elapsed = (now - start).total_seconds()
                time_ratio = min(max(elapsed / total_span, 0.0), 1.0)
                progress_ratio = completed / required if required else 1.0
                if progress_ratio >= time_ratio + 0.1:
                    status = "ahead"
                elif progress_ratio < time_ratio - 0.08:
                    status = "behind"
                else:
                    status = "on_pace"

        rows.append(
            {
                "challenge_title": challenge.title,
                "classes_remaining": remaining,
                "days_until_deadline": days_until,
                "classes_per_week_needed": cpw,
                "status": status,
            }
        )

    return rows


def analyze_weekly_pace(user_id: str) -> dict:
    """Analyze whether the user is on pace to finish each active challenge by its deadline.

    Args:
        user_id: Authenticated user's id (string from JWT).

    Returns:
        dict with key ``pace_analysis``: list of per-challenge pace rows (title, remaining,
        days until deadline, classes per week needed, status on_pace|behind|ahead|no_deadline).
    """
    with app.app_context():
        return {"pace_analysis": _build_pace_analysis(user_id)}


def suggest_weekly_plan(user_id: str) -> dict:
    """Build a 7-day workout plan from pace analysis (max 5 class days, 2+ rest days).

    Args:
        user_id: Authenticated user's id (string from JWT).

    Returns:
        dict with key ``weekly_plan``: list of day, challenge, and reason entries.
    """
    with app.app_context():
        pace_rows = _build_pace_analysis(user_id)
        if not pace_rows:
            return {
                "weekly_plan": [],
                "message": "No active challenges with classes left — enroll in a challenge first!",
            }

        status_rank = {"behind": 0, "on_pace": 1, "ahead": 2, "no_deadline": 3}

        def sort_key(row):
            days = row.get("days_until_deadline")
            days_sort = days if days is not None else 9999
            cpw = row.get("classes_per_week_needed") or 0
            return (status_rank.get(row["status"], 9), days_sort, -cpw)

        prioritized = sorted(pace_rows, key=sort_key)

        weekly_plan = []
        challenge_idx = 0
        for day_slot, day_index in enumerate(_WEEKLY_PLAN_DAY_INDICES):
            if day_slot >= 5:
                break
            row = prioritized[challenge_idx % len(prioritized)]
            challenge_idx += 1

            title = row["challenge_title"]
            remaining = row["classes_remaining"]
            status = row["status"]
            days = row.get("days_until_deadline")
            cpw = row.get("classes_per_week_needed")

            if status == "behind" and days is not None:
                reason = (
                    f"You are behind — {remaining} class(es) left with only {days} day(s) "
                    f"until the deadline; aim for about {cpw} classes per week."
                )
            elif status == "on_pace" and cpw is not None:
                reason = (
                    f"You need about {cpw} class(es) per week to stay on pace — "
                    f"{remaining} left to finish."
                )
            elif status == "ahead":
                reason = (
                    f"You are ahead of schedule with {remaining} class(es) left — "
                    f"keep your momentum going."
                )
            elif status == "no_deadline":
                reason = (
                    f"{remaining} class(es) remaining — no deadline, so this is a "
                    f"great day to build consistency."
                )
            else:
                reason = f"{remaining} class(es) remaining toward this challenge."

            weekly_plan.append(
                {
                    "day": _WEEKDAY_NAMES[day_index],
                    "challenge": title,
                    "reason": reason,
                }
            )

        return {"weekly_plan": weekly_plan}


def get_motivational_context(user_id: str) -> dict:
    """Return motivating stats: classes logged, lifetime points, completions, and goals.

    Args:
        user_id: Authenticated user's id (string from JWT).

    Returns:
        dict with total_classes_completed, lifetime_points_earned, challenges_completed,
        closest_to_completion (title, classes_remaining), and points_available_from_active_challenges.
    """
    with app.app_context():
        uid = int(user_id)

        enrollments = Enrollment.query.filter_by(user_id=uid).all()
        total_classes = sum(e.classes_completed or 0 for e in enrollments)
        challenges_completed = sum(
            1 for e in enrollments if e.status == "completed"
        )

        lifetime_points = int(
            db.session.query(func.sum(PointTxn.delta))
            .filter(PointTxn.user_id == uid, PointTxn.delta > 0)
            .scalar()
            or 0
        )

        closest = None
        min_remaining = None
        points_available = 0

        for enrollment in enrollments:
            if enrollment.status != "active":
                continue
            challenge = db.session.get(Challenge, enrollment.challenge_id)
            if not challenge:
                continue
            remaining = max(
                challenge.required_classes - (enrollment.classes_completed or 0), 0
            )
            if remaining > 0:
                points_available += challenge.points_reward
                if min_remaining is None or remaining < min_remaining:
                    min_remaining = remaining
                    closest = {
                        "title": challenge.title,
                        "classes_remaining": remaining,
                    }

        return {
            "total_classes_completed": total_classes,
            "lifetime_points_earned": lifetime_points,
            "challenges_completed": challenges_completed,
            "closest_to_completion": closest,
            "points_available_from_active_challenges": points_available,
        }


GEMINI_CHAT_TOOLS = [
    get_user_balance,
    get_user_activity_summary,
    get_user_challenges,
    list_available_challenges,
    enroll_in_challenge,
    log_class_for_challenge,
    get_available_rewards,
    redeem_reward_for_user,
    analyze_weekly_pace,
    suggest_weekly_plan,
    get_motivational_context,
]


KASHE_CHAT_HELP_PROMPT = (
    "I can help you log classes, plan your week, check if you are on pace, "
    "motivate you with your stats, enroll in challenges, or redeem rewards. What would you like?"
)

KASHE_CHAT_TECH_BLIP = (
    "Kashé hit a brief hiccup with the AI backend. You can still tell me to log a "
    "class by challenge name, redeem a reward by name, or ask about your progress. "
    "What should we do?"
)

GEMINI_CHAT_GENERATE_TIMEOUT_SEC = 75.0


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


def _normalize_challenge_name_fragment(raw: str) -> str:
    """Collapse whitespace around a user-provided challenge phrase."""
    return re.sub(r"\s+", " ", (raw or "").strip())


def _looks_unhelpful_gemini_reply(reply: str) -> bool:
    """True when the model gives an empty or generic unhelpful refusal."""
    text = (reply or "").strip().lower()
    if not text:
        return True
    needles = (
        "sorry, i didn't understand",
        "sorry, i did not understand",
        "i'm sorry, i don't",
        "i am sorry, i don't",
        "i don't understand",
        "didn't understand that",
        "did not understand that",
        "i'm not sure",
        "i am not sure",
        "can't help with that",
        "cannot help with that",
        "as an ai",
        "i cannot assist",
        "i can't assist",
        "unable to help",
    )
    return any(n in text for n in needles)


def _is_affirmative_message(message: str) -> bool:
    """Short yes-style replies for pending enroll-then-log prompts."""
    t = (message or "").strip().lower()
    if not t or len(t) > 80:
        return False
    return bool(
        re.match(
            r"^(yes+|yeah+|yep+|sure+|ok+|okay+|y\b|\bplease\b|do\s+it|absolutely|\bfine\b|"
            r"sounds?\s+good|go\s+ahead|that'?s\s+fine|that\s+is\s+fine|"
            r"let'?s\s+do\s+it)([\s!.?,]|$)",
            t,
        )
    )


def _catalog_active_challenge_names() -> str:
    rows = Challenge.query.filter(Challenge.is_active.is_(True)).order_by(Challenge.title).all()
    return ", ".join(c.title for c in rows[:14]) if rows else "No open challenges right now."


def _extract_log_class_challenge_title(message: str):
    """Detect log-a-class intent; return normalized challenge name fragment or None."""
    text = (message or "").strip()
    if not text:
        return None
    patterns = (
        r"log\s+(?:a\s+)?class\s+(?:for|on|toward|to|in)\s+(.+)",
        r"(?:please\s+)?(?:can\s+you\s+)?(?:could\s+you\s+)?log\s+(?:a\s+)?class\s+(?:for|on|toward|to|in)\s+(.+)",
        r"record\s+(?:a\s+)?class\s+(?:for|on|toward|to|in)\s+(.+)",
        r"(?:add|count|credit)\s+(?:a\s+)?class\s+(?:for|on|toward|to|in)\s+(.+)",
        r"(?:mark|check)\s+(?:a\s+)?class\s+(?:for|on|toward|to|in)\s+(.+)",
        r"(?:i\s+)?(?:just\s+)?(?:finished|completed|did)\s+(?:a\s+)?class\s+(?:for|on|at|in)\s+(.+)",
    )
    for pat in patterns:
        m = re.search(pat, text, re.I | re.S)
        if not m:
            continue
        title = _normalize_challenge_name_fragment(m.group(1))
        title = re.sub(
            r"\s+(please|thanks|thank\s+you)[\s.!?,]*$",
            "",
            title,
            flags=re.I,
        ).strip()
        title = title.strip().strip('"\'')
        title = title.rstrip(".,;!?")
        title = _normalize_challenge_name_fragment(title)
        if title:
            return title
    return None


def _extract_enroll_challenge_title(message: str):
    """Detect enroll intent; return normalized challenge fragment."""
    text = (message or "").strip()
    if not text:
        return None
    patterns = (
        r"enroll\s+(?:me\s+)?(?:in|into|for|on)\s+(.+)",
        r"(?:sign|put)\s+(?:me\s+)?up\s+for\s+(.+)",
        r"join\s+me\s+(?:for|in|on)\s+(.+)",
        r"join\s+(.+)",
        r"(?:register|add)\s+me\s+(?:for|in|on)\s+(.+)",
    )
    for pat in patterns:
        m = re.search(pat, text, re.I | re.S)
        if not m:
            continue
        title = _normalize_challenge_name_fragment(m.group(1)).rstrip(".,;!?\"'")
        if title:
            return title
    return None


def _extract_redeem_reward_title(message: str):
    """Detect redeem intent; return normalized reward name fragment."""
    text = (message or "").strip()
    if not text:
        return None
    patterns = (
        r"redeem\s+(?:my\s+)?(?:points\s+(?:for|on)\s+)?(.+)",
        r"(?:cash\s+in|exchange)\s+(?:my\s+)?points\s+for\s+(.+)",
        r"(?:claim|get)\s+(?:the\s+)?(?:reward\s+)?(?:for\s+)?(.+)",
    )
    for pat in patterns:
        m = re.search(pat, text, re.I | re.S)
        if not m:
            continue
        frag = _normalize_challenge_name_fragment(m.group(1)).rstrip(".,;!?\"'")
        frag = re.sub(
            r"\s+(please|thanks|thank\s+you)[\s.!?,]*$",
            "",
            frag,
            flags=re.I,
        ).strip()
        if frag:
            return frag
    return None


def _format_log_class_success_reply(result: dict, user_fragment: str) -> str:
    title = result.get("challenge_title") or user_fragment
    n = result.get("classes_completed", 0)
    if result.get("completed"):
        pts = result.get("points_earned", 0)
        return (
            f"Done — you finished {title}! You completed {n} classes and earned {pts} points. "
            f"Check Rewards to see what you can redeem next."
        )
    return (
        f"Logged one class toward {title}. You are now at {n} classes in this challenge. "
        f"Keep going — you are getting closer to the finish line."
    )


def _extract_weekly_plan_intent(message: str) -> bool:
    t = (message or "").strip().lower()
    if not t:
        return False
    patterns = (
        r"plan\s+my\s+week",
        r"help\s+me\s+plan",
        r"what\s+should\s+i\s+do\s+this\s+week",
        r"weekly\s+plan",
        r"schedule\s+my\s+week",
        r"workout\s+plan\s+for\s+the\s+week",
    )
    return any(re.search(p, t) for p in patterns)


def _extract_pace_intent(message: str) -> bool:
    t = (message or "").strip().lower()
    if not t:
        return False
    phrases = (
        "am i on pace",
        "on pace",
        "will i finish in time",
        "finish in time",
        "behind schedule",
        "behind on my",
        "catch up",
        "pace check",
        "enough time to finish",
    )
    if any(p in t for p in phrases):
        return True
    return bool(re.search(r"can\s+i\s+finish\s+.+\s+in\s+time", t))


def _extract_motivation_intent(message: str) -> bool:
    t = (message or "").strip().lower()
    if not t:
        return False
    needles = (
        "motivate",
        "discouraged",
        "struggling",
        "give up",
        "need encouragement",
        "feeling stuck",
        "hard to stay",
        "keep going",
        "cheer me up",
    )
    return any(n in t for n in needles)


def _format_pace_reply(pace_rows: list) -> str:
    if not pace_rows:
        return (
            "◇ Pace check\n\n"
            "No active challenges with classes left.\n\n"
            "› Enroll in one challenge and log your first class this week."
        )
    lines = ["◇ Pace check", ""]
    for row in pace_rows:
        title = row["challenge_title"]
        remaining = row["classes_remaining"]
        status = row["status"]
        days = row.get("days_until_deadline")
        cpw = row.get("classes_per_week_needed")
        if status == "no_deadline":
            lines.append(f"{title}")
            lines.append(f"· {remaining} classes left · no deadline")
        elif status == "behind":
            lines.append(f"{title}")
            lines.append(f"● Behind · {remaining} left · {days} days")
            lines.append(f"· Need ~{cpw} classes per week")
        elif status == "ahead":
            lines.append(f"{title}")
            lines.append(f"○ Ahead · {remaining} left · {days} days")
        else:
            lines.append(f"{title}")
            lines.append(f"· On pace · {remaining} left · {days} days")
            lines.append(f"· ~{cpw} classes per week")
        lines.append("")
    lines.append("› Schedule your next class while the window is still open.")
    return "\n".join(lines).rstrip()


def _format_weekly_plan_reply(plan_data: dict) -> str:
    plan = plan_data.get("weekly_plan") or []
    if not plan:
        return plan_data.get("message") or (
            "◇ Weekly plan\n\n"
            "No active enrollments to schedule.\n\n"
            "› Join a challenge first, then ask me to plan your week."
        )
    lines = ["◆ Your week", "· One class per day · two rest days minimum", ""]
    for entry in plan:
        lines.append(f"{entry['day']} · {entry['challenge']}")
        lines.append(f"› {entry['reason']}")
        lines.append("")
    lines.append("› Protect two rest days — recovery is part of the work.")
    return "\n".join(lines).rstrip()


def _format_motivation_reply(ctx: dict) -> str:
    total = ctx.get("total_classes_completed", 0)
    lifetime = ctx.get("lifetime_points_earned", 0)
    done = ctx.get("challenges_completed", 0)
    closest = ctx.get("closest_to_completion")
    points_avail = ctx.get("points_available_from_active_challenges", 0)

    lines = ["◇ Your numbers", ""]
    lines.append(f"· {total} classes logged")
    lines.append(f"· {lifetime} lifetime points")
    lines.append(f"· {done} challenges completed")
    if closest:
        lines.append("")
        lines.append(f"◆ Closest finish")
        lines.append(f"· {closest['title']}")
        lines.append(f"· {closest['classes_remaining']} class(es) remaining")
    if points_avail:
        lines.append("")
        lines.append(f"· {points_avail} points still on the table from active challenges")
    lines.append("")
    lines.append("› Log one class today — momentum compounds.")
    return "\n".join(lines)


def _iter_sse_text_chunks(text: str):
    """Split text into tokens for typewriter-style SSE (words and whitespace)."""
    if not text:
        return
    for token in re.findall(r"\S+|\s+", text):
        if token:
            yield token


def _sse_payload_line(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _compute_chat_reply_or_none(
    uid: str,
    message_str: str,
    history,
    pending_challenge_title: str,
):
    """Return (reply, pending_challenge_title) for deterministic paths, or None for Gemini."""
    if pending_challenge_title and _is_affirmative_message(message_str):
        en = enroll_in_challenge(uid, pending_challenge_title)
        if not en.get("success"):
            low = (en.get("message") or "").lower()
            if "already enrolled" not in low:
                return (en["message"], pending_challenge_title)

        prefix = (en["message"] + " ") if en.get("success") else ""
        loc = log_class_for_challenge(uid, pending_challenge_title)
        if loc.get("success"):
            return (
                prefix + _format_log_class_success_reply(loc, pending_challenge_title),
                None,
            )
        return (prefix + (loc.get("message") or "Could not log that class."), None)

    log_frag = _extract_log_class_challenge_title(message_str)
    if log_frag:
        tr = log_class_for_challenge(uid, log_frag)
        if tr.get("success"):
            return (_format_log_class_success_reply(tr, log_frag), None)
        if tr.get("reason") == "not_enrolled":
            ct = tr.get("challenge_title") or log_frag
            return (
                f"You're not enrolled in {ct} yet. Want me to enroll you first? "
                f"Say yes when you are ready.",
                ct,
            )
        if tr.get("reason") == "already_completed":
            ct = tr.get("challenge_title") or log_frag
            return (
                f"You already completed {ct}. Try logging toward another active challenge, "
                f"or enroll in something new from the Challenges tab.",
                None,
            )
        cat = _catalog_active_challenge_names()
        return (
            f"I could not match that to a challenge name. Open challenges right now: {cat}.",
            None,
        )

    enroll_frag = _extract_enroll_challenge_title(message_str)
    if enroll_frag:
        er = enroll_in_challenge(uid, enroll_frag)
        return (er["message"], None)

    redeem_frag = _extract_redeem_reward_title(message_str)
    if redeem_frag:
        rr = redeem_reward_for_user(uid, redeem_frag)
        if rr.get("success"):
            return (
                f"Redeemed {rr['reward_title']}! Your code is {rr['code']}. "
                f"Save it for checkout.",
                None,
            )
        return (rr.get("message") or KASHE_CHAT_HELP_PROMPT, None)

    if _extract_weekly_plan_intent(message_str):
        plan_data = suggest_weekly_plan(uid)
        return (_format_weekly_plan_reply(plan_data), None)

    if _extract_pace_intent(message_str):
        pace_data = analyze_weekly_pace(uid)
        return (_format_pace_reply(pace_data.get("pace_analysis") or []), None)

    if _extract_motivation_intent(message_str):
        ctx = get_motivational_context(uid)
        return (_format_motivation_reply(ctx), None)

    return None


def _gemini_reply_text(user_id, message_str: str, history) -> str:
    """Non-streaming Gemini reply (tools enabled)."""
    contents = _chat_history_to_contents(history or [], message_str)
    if not contents:
        return ""

    system_instruction = CHAT_SYSTEM_INSTRUCTION.format(
        authenticated_user_id=user_id
    )
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    def _run_model():
        return client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=GEMINI_CHAT_TOOLS,
            ),
        )

    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_run_model)
        response = fut.result(timeout=GEMINI_CHAT_GENERATE_TIMEOUT_SEC)

    reply = (response.text or "").strip()
    if _looks_unhelpful_gemini_reply(reply):
        reply = KASHE_CHAT_HELP_PROMPT
    return reply


def _gemini_text_chunks(user_id, message_str: str, history):
    """Yield Gemini text chunks; falls back to chunked full response on stream errors."""
    contents = _chat_history_to_contents(history or [], message_str)
    if not contents:
        return

    system_instruction = CHAT_SYSTEM_INSTRUCTION.format(
        authenticated_user_id=user_id
    )
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=GEMINI_CHAT_TOOLS,
    )

    try:
        stream = client.models.generate_content_stream(
            model="gemini-2.5-flash",
            contents=contents,
            config=config,
        )
        saw_text = False
        for chunk in stream:
            text = getattr(chunk, "text", None) or ""
            if text:
                saw_text = True
                yield text
        if saw_text:
            return
    except Exception as err:
        print(f"Gemini stream error: {err}")

    try:
        reply = _gemini_reply_text(user_id, message_str, history)
        yield from _iter_sse_text_chunks(reply)
    except FuturesTimeout:
        yield from _iter_sse_text_chunks(KASHE_CHAT_TECH_BLIP)
    except Exception as err:
        print(f"Gemini fallback error: {err}")
        yield from _iter_sse_text_chunks(KASHE_CHAT_TECH_BLIP)


def _chat_sse_generator(
    uid: str, user_id, message_str: str, history, pending_challenge_title: str
):
    """SSE stream: meta (optional) → text chunks → [DONE]."""
    try:
        resolved = _compute_chat_reply_or_none(
            uid, message_str, history, pending_challenge_title
        )

        if resolved is not None:
            reply, pending_out = resolved
            if pending_out:
                yield _sse_payload_line(
                    {"meta": {"pending_challenge_title": pending_out}}
                )
            for piece in _iter_sse_text_chunks(reply):
                yield _sse_payload_line({"chunk": piece})
            yield "data: [DONE]\n\n"
            return

        contents = _chat_history_to_contents(history or [], message_str)
        if not contents:
            yield _sse_payload_line({"error": "message is required"})
            yield "data: [DONE]\n\n"
            return

        for piece in _gemini_text_chunks(user_id, message_str, history):
            yield _sse_payload_line({"chunk": piece})
        yield "data: [DONE]\n\n"
    except FuturesTimeout:
        for piece in _iter_sse_text_chunks(KASHE_CHAT_TECH_BLIP):
            yield _sse_payload_line({"chunk": piece})
        yield "data: [DONE]\n\n"
    except Exception as err:
        print(f"Chat stream error: {err}")
        for piece in _iter_sse_text_chunks(KASHE_CHAT_TECH_BLIP):
            yield _sse_payload_line({"chunk": piece})
        yield "data: [DONE]\n\n"


@app.route("/api/chat/context", methods=["GET"])
@jwt_required()
def chat_context():
    """Activity summary + first name for clients (e.g. opening message builders)."""
    user_id = get_jwt_identity()
    user = models.User.query.get(int(user_id))
    first_name = ""
    if user and user.name:
        parts = user.name.strip().split()
        first_name = parts[0] if parts else ""
    summary = _build_activity_summary(user_id)
    return jsonify({"first_name": first_name or "there", **summary}), 200


@app.route("/api/chat/greeting", methods=["POST"])
@jwt_required()
def chat_greeting():
    """Personalized opening line from Gemini using live user data."""
    user_id = get_jwt_identity()
    user = models.User.query.get(int(user_id))
    if not user:
        return jsonify({"error": "User not found"}), 404

    summary = _build_activity_summary(user_id)
    close_to_finish = []
    for e in summary["enrollments"]:
        if e.get("status") != "active":
            continue
        remaining = e["required_classes"] - e["classes_completed"]
        if 0 < remaining <= 2:
            close_to_finish.append(
                {
                    "title": e["title"],
                    "classes_completed": e["classes_completed"],
                    "required_classes": e["required_classes"],
                    "classes_remaining": remaining,
                }
            )

    balance = summary["balance"]
    affordable = []
    for r in Reward.query.filter_by(is_active=True).all():
        if r.points_cost <= balance:
            affordable.append({"title": r.title, "points_cost": r.points_cost})

    payload = {
        "user_full_name": user.name,
        "balance_points": balance,
        "enrollments": summary["enrollments"],
        "challenges_close_to_completion": close_to_finish,
        "recent_point_transactions": summary["recent_point_txns"],
        "affordable_reward_titles": [x["title"] for x in affordable[:10]],
    }
    facts = json.dumps(payload, indent=2)
    user_first = user.name.strip().split()[0] if user.name else "there"

    try:
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            text=(
                                "Here is the user's live Kashé data. "
                                "Write only the opening message per your instructions.\n\n"
                                + facts
                            )
                        )
                    ],
                )
            ],
            config=types.GenerateContentConfig(
                system_instruction=GREETING_SYSTEM_INSTRUCTION,
            ),
        )
        greeting = (response.text or "").strip()
        if not greeting:
            greeting = (
                f"Hi {user_first}, I'm Kai! "
                "Ask me to plan your week, check your pace, or log a class toward any challenge."
            )
        return jsonify({"greeting": greeting}), 200
    except Exception as err:
        print(f"Greeting error: {str(err)}")
        return jsonify({"error": f"Greeting service error: {str(err)}"}), 500


def _parse_chat_request_body(data):
    """Validate chat POST body; returns (message_str, history, pending_title) or error response."""
    message = data.get("message")
    history = data.get("history")

    if not message or not str(message).strip():
        return None, (jsonify({"error": "message is required"}), 400)

    if history is not None and not isinstance(history, list):
        return None, (jsonify({"error": "history must be an array when provided"}), 400)

    message_str = str(message).strip()
    pending_raw = (data.get("pending_challenge_title") or "").strip()
    pending_challenge_title = _normalize_challenge_name_fragment(pending_raw)
    return (message_str, history, pending_challenge_title), None


@app.route('/api/chat', methods=['POST'])
@jwt_required()
def chat():
    """Chat: deterministic handlers for common intents, then Gemini with tools."""
    data = request.get_json() or {}
    parsed, err = _parse_chat_request_body(data)
    if err:
        return err

    message_str, history, pending_challenge_title = parsed
    user_id = get_jwt_identity()
    uid = str(user_id)

    def _ok(reply: str, pending=None):
        return jsonify(
            {"reply": reply, "pending_challenge_title": pending}
        ), 200

    resolved = _compute_chat_reply_or_none(
        uid, message_str, history, pending_challenge_title
    )
    if resolved is not None:
        reply, pending_out = resolved
        return _ok(reply, pending_out)

    contents = _chat_history_to_contents(history or [], message_str)
    if not contents:
        return jsonify({"error": "message is required"}), 400

    try:
        reply = _gemini_reply_text(user_id, message_str, history)
        return _ok(reply, None)
    except FuturesTimeout:
        return _ok(KASHE_CHAT_TECH_BLIP, None)
    except Exception as err:
        print(f"Chat error: {str(err)}")
        return _ok(KASHE_CHAT_TECH_BLIP, None)


@app.route('/api/chat/stream', methods=['POST'])
@jwt_required()
def chat_stream():
    """Chat over Server-Sent Events — same logic as /api/chat with streamed tokens."""
    data = request.get_json() or {}
    parsed, err = _parse_chat_request_body(data)
    if err:
        return err

    message_str, history, pending_challenge_title = parsed
    user_id = get_jwt_identity()
    uid = str(user_id)

    return Response(
        stream_with_context(
            _chat_sse_generator(uid, user_id, message_str, history, pending_challenge_title)
        ),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    socketio.run(app, debug=True)
