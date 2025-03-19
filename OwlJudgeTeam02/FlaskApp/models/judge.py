# models/FlaskApp.py

from judge.app import db

class judge(db.Model):
    judge_id = db.Column(db.Integer, primary_key=True)
    judge_name = db.Column(db.String(50), nullable=False)
    projects_assigned = db.Column(db.Integer)
    perc_complete = db.Column(db.Integer)
    credential_id = db.Column(db.Integer)

# add more functionality as needed