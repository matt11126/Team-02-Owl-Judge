# models/group.py

from app import db 

class Group(db.Model):
    group_id = db.Column(db.Integer, primary_key=True)
    group_name = db.Column(db.String(50), nullable=False)
    project_id = db.Column(db.Integer)

# add more functionality as needed