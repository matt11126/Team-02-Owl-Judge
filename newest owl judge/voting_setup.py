from app import app
import voting_route  # This registers the /voting route with your app

if __name__ == '__main__':
    app.run(debug=True)
