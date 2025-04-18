from . import BaseModel

# ✅ Schéma pour la requête de récupération de mot de passe
class ForgotPasswordRequest(BaseModel):
    email: str

# Schéma pour la requête de récupération de code type OTP
class OTPRequest(BaseModel):
    email: str
    code: str

# Schéma pour la requête de récupération de code type OTP
class ResetPasswordRequest(BaseModel):
    email: str
    code: str
    new_password: str
    confirm_password: str
