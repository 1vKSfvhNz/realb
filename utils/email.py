from os import getenv
import smtplib
import aiosmtplib
from email.message import EmailMessage
from jinja2 import Template
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

SMTP_HOST = getenv("SMTP_HOST")
SMTP_PORT = int(getenv("SMTP_PORT", 587))
SMTP_USER = getenv("SMTP_USER")
SMTP_PASSWORD = getenv("SMTP_PASSWORD")

def render_template(file_path: str, context: dict) -> str:
    with open(f"templates/{file_path}", "r", encoding="utf-8") as file:
        template = Template(file.read())
    return template.render(context)

def send_email_init(to_email: str, subject: str, body_file: str, context: dict) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = subject
    
    # Charger et rendre le contenu HTML avec Jinja
    html_content = render_template(body_file, context)
    msg.set_content(html_content, subtype='html')    
    return msg

# Fonction synchrone (optionnel)
def send_email_sync(to_email: str, subject: str, body_file: str, context: dict):
    msg = send_email_init(to_email, subject, body_file, context)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)

async def send_email_async(to_email: str, subject: str, body_file: str, context: dict):
    msg = send_email_init(to_email, subject, body_file, context)
    try:
        response = await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            start_tls=True,
            username=SMTP_USER,
            password=SMTP_PASSWORD,
        )
        print("✅ Email envoyé avec succès.")
        print("📬 Réponse SMTP :", response)
        return True
    except aiosmtplib.SMTPException as e:
        print("❌ Échec de l'envoi de l'email :", e)
        return False
