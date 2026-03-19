from flask import Flask, request, jsonify
import psycopg2
import uuid
import os

app = Flask(__name__)

# The URL to the database is sensitive, so we get it from an environment variable we set in the server host
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost/fallback")

@app.route('/', methods=['GET'])
def health_check():
    # this should show when opening the link in the browser so we can see if the server is running correcrtly
    return "🟢 KitchenMate Server is Awake and Running!", 200

def get_db_connection():
    # Returns a connection to the cloud database
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

# Run database setup on startup
# init_db() only necessary if the table doesn't exist yet

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    role = data.get('role')
    password = data.get('password') 
    
    # Generate a session token to send back to Android
    session_token = f"kitchenmate_token_{uuid.uuid4().hex}"

    # Open the database connection using our helper function
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Save the sent values to the cloud database
        cur.execute("INSERT INTO users (name, email, role, password) VALUES (%s, %s, %s, %s)", (name, email, role, password))
        conn.commit()
        print(f"Success: Saved {name} to the cloud database")
    except Exception as e:
        # Since the email should be unique, this will catch attempts to register with an email that's already in use
        return jsonify({"message": "Error saving user", "error": str(e)}), 400
    finally:
        cur.close()
        conn.close()

    return jsonify({
        "token": session_token,
        "role": role,
        "message": "User registered and saved successfully!"
    }), 200

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    # Open the database connection
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Search for the user by email
        cur.execute("SELECT id, name, role, password FROM users WHERE email = %s", (email,))
        user = cur.fetchone() # Fetches the first matching row, or none if it doesn't exist

        # Check if the user exists and the password matches
        # user[3] is the password column from our SELECT statement above
        if user and user[3] == password:
            # Success! Generate a session token
            session_token = f"kitchenmate_token_{uuid.uuid4().hex}"
            return jsonify({
                "token": session_token, 
                "role": user[2], # user[2] is the role column from our SELECT statement above
                "message": f"Welcome back, {user[1]}!" # user[1] is their name
            }), 200
        else:
            # Fail: wrong email or password
            return jsonify({"message": "Invalid email or password"}), 401
            
    except Exception as e:
        return jsonify({"message": "Server error", "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000)