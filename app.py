import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_socketio import SocketIO
from models import ChatMessage
from database import db
from peewee import fn
from peewee import PostgresqlDatabase, SqliteDatabase

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

# SocketIO, compatible avec eventlet / gevent / threading. En prod: worker eventlet.
# socketio = SocketIO(app, cors_allowed_origins="*")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="gevent")


MAX_MESSAGES = 50

@app.before_request
def ensure_tables():
    db.create_tables([ChatMessage], safe=True)


def enforce_cap(max_rows=MAX_MESSAGES):
    """Garde au plus `max_rows` messages en supprimant les plus anciens."""
    with db.atomic():
        total = ChatMessage.select(fn.COUNT(ChatMessage.id)).scalar()
        if total and total > max_rows:
            excess = total - max_rows
            # Récupère les IDs les plus anciens à supprimer
            old_ids = (ChatMessage
                       .select(ChatMessage.id)
                       .order_by(ChatMessage.created_at.asc())
                       .limit(excess))
            # Supprime en un coup
            (ChatMessage
             .delete()
             .where(ChatMessage.id.in_(old_ids))
             .execute())
            

@app.route("/", methods=["GET"])
def index():
    messages = (ChatMessage
                .select()
                .order_by(ChatMessage.created_at.desc()))
    return render_template("index.html", messages=messages)

@app.post("/api/chat")
def api_chat():
    data = request.get_json(silent=True) or {}
    prenom = (data.get("prenom") or "").strip()
    filiaire = (data.get("filiaire") or "").strip()
    commentaire = (data.get("commentaire") or "").strip()

    if not prenom or not filiaire or not commentaire:
        return jsonify({"ok": False, "error": "Tous les champs sont requis."}), 400

    prenom = prenom[:50]
    filiaire = filiaire[:120]
    commentaire = commentaire[:2000]

    msg = ChatMessage.create(prenom=prenom, filiaire=filiaire, commentaire=commentaire)
    
    # On appelle enforce_cap() juste après chaque création de message, pour conserver 50 MESSAGES, PAS PLUS.
    enforce_cap()   # supprime les plus anciens au-delà de 50
    
    # Diffuse à tous les clients connectés
    socketio.emit("chat:new", {
        "prenom": msg.prenom,
        "filiaire": msg.filiaire,
        "commentaire": msg.commentaire
    })

    return jsonify({"ok": True})


@app.post("/post")
def post_form():
    prenom = (request.form.get("prenom") or "").strip()
    filiaire = (request.form.get("filiaire") or "").strip()
    commentaire = (request.form.get("commentaire") or "").strip()
    if prenom and filiaire and commentaire:
        msg = ChatMessage.create(prenom=prenom[:50], filiaire=filiaire[:120], commentaire=commentaire[:2000])
        
        # On appelle enforce_cap() juste après chaque création de message, pour conserver 50 MESSAGES, PAS PLUS.
        enforce_cap()  # supprime les plus anciens au-delà de 50
        
        # Diffuse à tous les clients connectés
        socketio.emit("chat:new", {"prenom": msg.prenom, "filiaire": msg.filiaire, "commentaire": msg.commentaire})
    return redirect(url_for("index"))


# Comment savoir quelle BD est utilisée (à coup sûr) ?
# (Optionnel) mini endpoint pour vérifier en live
# → Aller sur http://127.0.0.1:5000/debug/db et on saura.
@app.get("/debug/db")
def debug_db():
    if isinstance(db, PostgresqlDatabase):
        kind = "postgresql"
        name = db.database
        host = getattr(db, 'host', None)
    elif isinstance(db, SqliteDatabase):
        kind = "sqlite"
        name = db.database  # chemin du fichier .db
        host = None
    else:
        kind = type(db).__name__
        name = getattr(db, 'database', None)
        host = None
    return jsonify({"backend": kind, "database": name, "host": host})


if __name__ == "__main__":
    # En dev: websocket + auto-reload pratique
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
