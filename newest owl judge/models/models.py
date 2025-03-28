from database import db
from app import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

# The User model used for authentication (you can adjust as needed)
class User(db.Model):
    __tablename__ = 'User'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(20), default='user', nullable=False)

    def __repr__(self):
        return f'<User {self.email} - Role: {self.role}>'


class Judge(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<Judge {self.email}>'
# Additional tables

class Students(db.Model):
    __tablename__ = 'Students'
    student_id = db.Column(db.Integer, primary_key=True)
    student_name = db.Column(db.String(50))
    group_id = db.Column(db.Integer)

class Groups(db.Model):
    __tablename__ = 'Groups'
    group_id = db.Column(db.Integer, primary_key=True)
    group_name = db.Column(db.String(50))
    project_id = db.Column(db.Integer)

class Projects(db.Model):
    __tablename__ = 'Projects'
    project_id = db.Column(db.Integer, primary_key=True)
    project_name = db.Column(db.String(50))
    group_id = db.Column(db.Integer)

class Rankings(db.Model):
    __tablename__ = 'Rankings'
    # Added an id field as a primary key since one is required.
    id = db.Column(db.Integer, primary_key=True)
    ranking = db.Column(db.Integer)
    project_name = db.Column(db.String(50))
    score = db.Column(db.Integer)
    project_id = db.Column(db.Integer)

class Scores(db.Model):
    __tablename__ = 'Scores'
    score_id = db.Column(db.Integer, primary_key=True)
    score_given = db.Column(db.Integer)
    project_id = db.Column(db.Integer)
    judge_id = db.Column(db.Integer)

class Judges(db.Model):
    __tablename__ = 'Judges'
    judge_id = db.Column(db.Integer, primary_key=True)
    judge_name = db.Column(db.String(50))
    projects_assigned = db.Column(db.Integer)
    perc_complete = db.Column(db.Integer)
    credential_id = db.Column(db.Integer)

class Credentials(db.Model):
    __tablename__ = 'Credentials'
    credential_id = db.Column(db.Integer, primary_key=True)
    judge_name = db.Column(db.String(50))
    username_encrypted = db.Column(db.String(255))
    password_encrypted = db.Column(db.String(255))
    judge_id = db.Column(db.Integer)
    permission_id = db.Column(db.Integer)


class Permissions(db.Model):
    __tablename__ = 'Permissions'
    permission_id = db.Column(db.Integer, primary_key=True)
    permission_name = db.Column(db.String(50))
    can_read = db.Column(db.Boolean)
    can_cast = db.Column(db.Boolean)
    can_modify = db.Column(db.Boolean)
    is_developer = db.Column(db.Boolean)
