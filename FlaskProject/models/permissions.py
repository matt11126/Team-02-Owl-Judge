# models/permissions.py

from app import db 

class Permission(db.Model):
    permission_id = db.Column(db.Integer, primary_key=True)
    permission_name = db.Column(db.String(50), nullable=False)
    can_read = db.Column(db.Boolean)
    can_cast = db.Column(db.Boolean)
    can_modify = db.Column(db.Boolean)
    is_developer = db.Column(db.Boolean)

# add more functionality as needed