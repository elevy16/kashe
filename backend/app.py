import os

from flask import Flask, jsonify
from flask_jwt_extended import JWTManager
from flask_sqlalchemy import SQLAlchemy


app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", "sqlite:///kashe_dev.db"
)
app.config["JWT_SECRET_KEY"] = os.getenv(
    "JWT_SECRET_KEY", "dev-secret-change-in-production"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Extensions
db = SQLAlchemy(app)
jwt = JWTManager(app)

# Import models after extensions are initialized to avoid circular imports
import models  # noqa: F401

# Ensure tables are created on startup
with app.app_context():
    db.create_all()


@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "ok", "app": "Kashé API"})


if __name__ == "__main__":
    app.run(debug=True)
