# models/ranking.py

from app import db 

class Ranking(db.Model):
    ranking = db.Column(db.Integer)
    project_name = db.Column(db.String(50), nullable=False)
    score = db.Column(db.Integer)
    project_id = db.Column(db.Integer)

# add more functionality as needed