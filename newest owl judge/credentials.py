# models/credentials.py

from app import db 

class Credential(db.Model):
    credential_id = db.Column(db.Integer, primary_key=True)
    judge_name = db.Column(db.String(50), nullable=False)
    username_encrypted = db.Column(db.String(128))
    password_encrypted = db.Column(db.String(128))
    judge_id = db.Column(db.Integer)
    permission_id = db.Column(db.Integer)

# add more functionality as needed