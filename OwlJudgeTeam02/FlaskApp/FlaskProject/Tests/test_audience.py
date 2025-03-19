# New: Test Audience route that retrieves all database data
@app.route('/test_audience_db')
def test_audience_db():
    # Import your ORM models. Adjust these import statements to match your project structure.
    from models.models import Student
    from models.models import Group       # (Assuming the model for Groups is named "Group")
    from models.models import Project
    from models.models import Ranking
    from models.models import Score
    from models.models import Judge
    from models.models import Credential
    from models.models import Permission

    # Helper function to convert a SQLAlchemy model instance to a dict,
    # removing the internal _sa_instance_state which is not serializable.
    def model_to_dict(model):
        d = model.__dict__.copy()
        d.pop('_sa_instance_state', None)
        return d

    # Retrieve all records from each table.
    students = [model_to_dict(s) for s in Student.query.all()]
    groups = [model_to_dict(g) for g in Group.query.all()]
    projects = [model_to_dict(p) for p in Project.query.all()]
    rankings = [model_to_dict(r) for r in Ranking.query.all()]
    scores = [model_to_dict(s) for s in Score.query.all()]
    judges = [model_to_dict(j) for j in Judge.query.all()]
    credentials = [model_to_dict(c) for c in Credential.query.all()]
    permissions = [model_to_dict(p) for p in Permission.query.all()]

    # Package all the data into one dictionary.
    data = {
        "students": students,
        "groups": groups,
        "projects": projects,
        "rankings": rankings,
        "scores": scores,
        "judges": judges,
        "credentials": credentials,
        "permissions": permissions
    }
    return jsonify(data)
