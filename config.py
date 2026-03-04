import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "postgresql://user:pass@localhost:5432/supermart"
    ).replace("postgres://", "postgresql://")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOW_STOCK_THRESHOLD  = int(os.environ.get("LOW_STOCK_THRESHOLD", 10))
    EXPIRY_WARNING_DAYS  = int(os.environ.get("EXPIRY_WARNING_DAYS", 30))
    MAIL_SERVER   = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT     = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_ENABLED  = os.environ.get("MAIL_ENABLED", "false").lower() == "true"
