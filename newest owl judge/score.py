# models/score.py

from app import db 

class Score(db.Model):
    score_id = db.Column(db.Integer, primary_key=True)
    score_given = db.Column(db.Integer)
    project_id = db.Column(db.Integer)
    judge_id = db.Column(db.Integer)

# add more functionality as needed