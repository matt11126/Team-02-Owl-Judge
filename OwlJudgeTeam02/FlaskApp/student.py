# models/students.py

from judge.models.judge import db

class Student(db.Model):
    student_id = db.Column(db.Integer, primary_key=True)
    student_name = db.Column(db.String(50), nullable=False)
    group_id = db.Column(db.Integer)

# add more functionality as needed
    