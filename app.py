from flask import Flask, request, jsonify
import psycopg2
import uuid
import os

app = Flask(__name__)

# Make sure your actual Neon URL is pasted here!
# This grabs the URL from Render when deployed, or uses a default string locally (DON'T put your real password in the default!)
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost/fallback")

def get_db_connection():
    # Connects to the Neon.tech cloud database
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
    
    # Generate a mock session token to send back to Android
    session_token = f"kitchenmate_token_{uuid.uuid4().hex}"

    # Open the database connection using our helper function (NO MORE SQLITE!)
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Save to Neon.tech using Postgres %s syntax
        cur.execute("INSERT INTO users (name, email, role, password) VALUES (%s, %s, %s, %s)", (name, email, role, password))
        conn.commit()
        print(f"Success: Saved {name} to the cloud database!")
    except Exception as e:
        # If the email already exists, it will trigger this error
        return jsonify({"message": "Error saving user", "error": str(e)}), 400
    finally:
        cur.close()
        conn.close()

    return jsonify({
        "token": session_token,
        "message": "User registered and saved successfully!"
    }), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000)