import sqlalchemy as db

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
  username_encrypted = db.Column()
  password_encrypted = db.Column()
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
