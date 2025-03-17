# models/project.py

from app import db 

class Project(db.Model):
    project_id = db.Column(db.Integer, primary_key=True)
    project_name = db.Column(db.String(50), nullable=False)
    group_id = db.Column(db.Integer)

# add more functionality as needed