import os
import smtplib
from email.mime.text import MIMEText
from pathlib import Path
from dotenv import load_dotenv

# Load variables from project .env regardless of the process working directory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv()


def _env(name, default=""):
    value = os.getenv(name, default)
    return value.strip() if isinstance(value, str) else default


def send_email(to_email, subject, text):
    sender_email = _env("EMAIL_SENDER", "eduquestalert@gmail.com")
    sender_password = _env("EMAIL_PASSWORD").replace(" ", "")
    smtp_host = _env("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(_env("SMTP_PORT", "465") or 465)
    smtp_use_ssl = _env("SMTP_USE_SSL", "true").lower() not in ("0", "false", "no")

    if not sender_password:
        print("Warning: EMAIL_PASSWORD not set in .env")
        return False

    msg = MIMEText(text, 'plain', 'utf-8')
    msg['Subject'] = subject
    msg['From'] = f"EduQuest <{sender_email}>"
    msg['To'] = to_email

    try:
        if smtp_use_ssl:
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
                server.login(sender_email, sender_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.send_message(msg)
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(
            "Error sending email: Gmail rejected credentials. "
            "Use a Google App Password for EMAIL_PASSWORD and check EMAIL_SENDER."
        )
        print(f"SMTP auth details: {e}")
        return False
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

def send_verification_code(email, code, mode="login"):
    if mode == "register":
        subject = "Подтверждение регистрации — EduQuest"
        text = f"Ваш код для подтверждения регистрации: {code}\nНикому не сообщайте этот код."
    elif mode == "change_email":
        subject = "Подтверждение смены почты — EduQuest"
        text = f"Ваш код для подтверждения смены почты: {code}\nЕсли вы не запрашивали смену почты, не сообщайте этот код."
    elif mode == "change_password":
        subject = "Подтверждение смены пароля — EduQuest"
        text = f"Ваш код для подтверждения смены пароля: {code}\nЕсли вы не запрашивали смену пароля, не сообщайте этот код."
    elif mode == "delete_account":
        subject = "Подтверждение удаления аккаунта — EduQuest"
        text = f"Ваш код для подтверждения удаления аккаунта: {code}\nЕсли вы не запрашивали удаление, немедленно смените пароль."
    else:
        subject = "Код подтверждения — EduQuest"
        text = f"Ваш код подтверждения для входа: {code}"
    
    return send_email(email, subject, text)
