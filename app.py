from flask import Flask, request, jsonify
import psycopg2
import uuid
import os
import json

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost/fallback")


def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                role TEXT NOT NULL,
                password TEXT NOT NULL,
                session_token TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS recipes (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                ingredients_json TEXT NOT NULL,
                instructions_json TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS inventories (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                emoji TEXT NOT NULL DEFAULT '📦',
                name TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 1.0,
                unit TEXT NOT NULL DEFAULT 'pcs',
                expires TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS favorite_recipes (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                recipe_name TEXT NOT NULL,
                UNIQUE (user_id, recipe_name),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        conn.commit()
    finally:
        cur.close()
        conn.close()


def get_user_id_from_request():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ")[1]

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE session_token = %s", (token,))
        user = cur.fetchone()
        return user[0] if user else None
    finally:
        cur.close()
        conn.close()


@app.route("/", methods=["GET"])
def health_check():
    return "KitchenMate Server is Awake and Running", 200


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    email = data.get("email", "").strip()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"message": "Email and password are required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT role, session_token FROM users WHERE email = %s AND password = %s",
            (email, password)
        )
        user = cur.fetchone()

        if not user:
            return jsonify({"message": "Invalid email or password"}), 401

        return jsonify({
            "token": user[1],
            "role": user[0],
            "message": "Login successful"
        }), 200

    except Exception as e:
        return jsonify({"message": "Database error", "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    role = data.get("role", "").strip()
    password = data.get("password", "")

    if not name or not email or not role or not password:
        return jsonify({"message": "All fields are required"}), 400

    session_token = f"kitchenmate_token_{uuid.uuid4().hex}"

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (name, email, role, password, session_token) VALUES (%s, %s, %s, %s, %s)",
            (name, email, role, password, session_token)
        )
        conn.commit()

        return jsonify({
            "token": session_token,
            "role": role,
            "message": "User registered and saved successfully"
        }), 200

    except Exception as e:
        return jsonify({"message": "Error saving user", "error": str(e)}), 400
    finally:
        cur.close()
        conn.close()


@app.route("/api/recipes", methods=["GET"])
def get_recipes():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, name, description, ingredients_json, instructions_json
            FROM recipes
            ORDER BY name ASC
        """)
        rows = cur.fetchall()

        recipes = []
        for row in rows:
            try:
                ingredients = json.loads(row[3]) if row[3] else []
            except Exception:
                ingredients = []

            try:
                instructions = json.loads(row[4]) if row[4] else []
            except Exception:
                instructions = []

            recipes.append({
                "id": row[0],
                "name": row[1],
                "description": row[2],
                "requiredIngredients": ingredients,
                "instructions": instructions
            })

        return jsonify(recipes), 200

    except Exception as e:
        return jsonify({"message": "Database error", "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/api/favorites", methods=["GET"])
def get_favorites():
    user_id = get_user_id_from_request()
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT recipe_name FROM favorite_recipes WHERE user_id = %s ORDER BY recipe_name ASC",
            (user_id,)
        )
        rows = cur.fetchall()
        favorite_names = [row[0] for row in rows]
        return jsonify(favorite_names), 200
    except Exception as e:
        return jsonify({"message": "Database error", "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/api/favorites/add", methods=["POST"])
def add_favorite():
    user_id = get_user_id_from_request()
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json() or {}
    recipe_name = data.get("recipe_name", "").strip()

    if not recipe_name:
        return jsonify({"message": "Recipe name is required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO favorite_recipes (user_id, recipe_name)
            VALUES (%s, %s)
            ON CONFLICT (user_id, recipe_name) DO NOTHING
        """, (user_id, recipe_name))
        conn.commit()
        return jsonify({"message": "Favorite added"}), 200
    except Exception as e:
        return jsonify({"message": "Database error", "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/api/favorites/remove", methods=["POST"])
def remove_favorite():
    user_id = get_user_id_from_request()
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json() or {}
    recipe_name = data.get("recipe_name", "").strip()

    if not recipe_name:
        return jsonify({"message": "Recipe name is required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM favorite_recipes WHERE user_id = %s AND recipe_name = %s",
            (user_id, recipe_name)
        )
        conn.commit()
        return jsonify({"message": "Favorite removed"}), 200
    except Exception as e:
        return jsonify({"message": "Database error", "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/api/inventory", methods=["GET"])
def get_inventory():
    user_id = get_user_id_from_request()
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, emoji, name, amount, unit, expires
            FROM inventories
            WHERE user_id = %s
            ORDER BY created_at DESC
        """, (user_id,))
        rows = cur.fetchall()

        inventory_list = []
        for row in rows:
            inventory_list.append({
                "id": row[0],
                "emoji": row[1],
                "name": row[2],
                "amount": row[3],
                "unit": row[4],
                "expires": row[5]
            })

        return jsonify(inventory_list), 200
    except Exception as e:
        return jsonify({"message": "Database error", "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/api/inventory/add", methods=["POST"])
def add_inventory_item():
    user_id = get_user_id_from_request()
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json() or {}
    emoji = data.get("emoji", "📦")
    name = data.get("name", "").strip()
    amount = float(data.get("amount", 1.0))
    unit = data.get("unit", "pcs").strip()
    expires = data.get("expires", "").strip()
    force_update = data.get("force_update", False)

    if not name:
        return jsonify({"message": "Item name is required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, amount, unit FROM inventories WHERE LOWER(name) = LOWER(%s) AND user_id = %s AND expires = %s",
            (name, user_id, expires)
        )
        existing_item = cur.fetchone()

        if existing_item:
            item_id, existing_amount, existing_unit = existing_item

            if existing_unit != unit and not force_update:
                return jsonify({
                    "error": "UNIT_MISMATCH",
                    "message": f"Unit mismatch for {name}."
                }), 409

            new_amount = float(existing_amount) + amount

            cur.execute(
                "UPDATE inventories SET amount = %s, unit = %s, expires = %s, emoji = %s WHERE id = %s",
                (new_amount, unit, expires, emoji, item_id)
            )
            conn.commit()
            return jsonify({"message": f"Combined! You now have {new_amount} {unit} of {name}."}), 200

        cur.execute(
            "INSERT INTO inventories (user_id, emoji, name, amount, unit, expires) VALUES (%s, %s, %s, %s, %s, %s)",
            (user_id, emoji, name, amount, unit, expires)
        )
        conn.commit()
        return jsonify({"message": f"Added {name} to your inventory!"}), 201

    except Exception as e:
        return jsonify({"message": "Database error", "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/api/inventory/delete/<int:item_id>", methods=["DELETE"])
def delete_inventory_item(item_id):
    user_id = get_user_id_from_request()
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM inventories WHERE id = %s AND user_id = %s",
            (item_id, user_id)
        )
        conn.commit()

        if cur.rowcount == 0:
            return jsonify({"message": "Item not found"}), 404

        return jsonify({"message": "Item deleted"}), 200
    except Exception as e:
        return jsonify({"message": "Database error", "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/api/inventory/consume/<int:item_id>", methods=["POST"])
def consume_inventory_item(item_id):
    user_id = get_user_id_from_request()
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json() or {}
    amount_to_remove = float(data.get("amount_to_consume", 0.0))

    if amount_to_remove <= 0:
        return jsonify({"message": "Amount to consume must be greater than 0"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT amount, unit FROM inventories WHERE id = %s AND user_id = %s",
            (item_id, user_id)
        )
        item = cur.fetchone()

        if not item:
            return jsonify({"message": "Item not found"}), 404

        current_amount = float(item[0])
        current_unit = item[1]
        new_amount = current_amount - amount_to_remove

        if new_amount < 0.001:
            cur.execute("DELETE FROM inventories WHERE id = %s", (item_id,))
            conn.commit()
            return jsonify({"message": "Item fully consumed", "action": "deleted"}), 200

        new_unit = current_unit
        if current_unit == "kg" and new_amount < 1.0:
            new_amount = new_amount * 1000
            new_unit = "g"
        elif current_unit in ("L", "Liter") and new_amount < 1.0:
            new_amount = new_amount * 1000
            new_unit = "ml"

        cur.execute(
            "UPDATE inventories SET amount = %s, unit = %s WHERE id = %s",
            (new_amount, new_unit, item_id)
        )
        conn.commit()
        return jsonify({"message": "Inventory updated", "action": "updated"}), 200

    except Exception as e:
        return jsonify({"message": "Database error", "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/api/inventory/update_expiry/<int:item_id>", methods=["PATCH"])
def update_expiry(item_id):
    user_id = get_user_id_from_request()
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json() or {}
    new_expires = data.get("expires", "").strip()

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT name, amount, unit FROM inventories WHERE id = %s AND user_id = %s",
            (item_id, user_id)
        )
        target_item = cur.fetchone()

        if not target_item:
            return jsonify({"message": "Item not found"}), 404

        name, amount, unit = target_item[0], target_item[1], target_item[2]

        cur.execute(
            "SELECT id, amount FROM inventories WHERE LOWER(name) = LOWER(%s) AND unit = %s AND expires = %s AND user_id = %s AND id != %s",
            (name, unit, new_expires, user_id, item_id)
        )
        matching_item = cur.fetchone()

        if matching_item:
            match_id, match_amount = matching_item[0], matching_item[1]
            new_amount = float(amount) + float(match_amount)

            cur.execute("UPDATE inventories SET amount = %s WHERE id = %s", (new_amount, match_id))
            cur.execute("DELETE FROM inventories WHERE id = %s", (item_id,))
            message = "Items merged successfully!"
        else:
            cur.execute(
                "UPDATE inventories SET expires = %s WHERE id = %s AND user_id = %s",
                (new_expires, item_id, user_id)
            )
            message = "Expiration date updated!"

        conn.commit()
        return jsonify({"message": message}), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"message": "Database error", "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", debug=False, port=port)