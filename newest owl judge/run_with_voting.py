from app import app
import voting_page  # This ensures the /voting route is registered

if __name__ == '__main__':
    app.run(debug=True)
