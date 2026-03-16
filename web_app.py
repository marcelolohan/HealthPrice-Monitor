import os
import sys
import re
import json
import uuid
import hashlib
import secrets
import threading
import subprocess
from datetime import datetime, date, timedelta
from functools import wraps
from flask import Flask, render_template, jsonify, request, session, redirect, url_for, send_file
import os

ADMIN_USER = os.getenv("ADMIN_USER")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

app = Flask(__name__, static_folder="static")
app.secret_key = os.environ.get("HPM_SECRET", "hpm-secret-2026-change-me")

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_BASE = os.path.join(BASE_DIR, "MAIN", "PASTAS DE DOWNLOADS")
CREDS_FILE    = os.path.join(BASE_DIR, "credentials.json")
CONFIG_FILE   = os.path.join(BASE_DIR, "config.json")
LOGS_DIR      = os.path.join(BASE_DIR, "MAIN", "LOGS")
os.makedirs(LOGS_DIR, exist_ok=True)

# ─── User helpers ─────────────────────────────────────────────────────────────

_config_lock = threading.Lock()

def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

def _make_user(username: str, password: str, role: str = "operator", name: str = "") -> dict:
    salt = secrets.token_hex(16)
    return {
        "id": uuid.uuid4().hex[:12],
        "username": username.strip().lower(),
        "name": name.strip() or username.strip(),
        "role": role,
        "salt": salt,
        "password_hash": _hash_password(password, salt),
        "created_at": datetime.now().isoformat(),
        "must_change_password": False,
    }

def load_config() -> dict:
    with _config_lock:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            # migrate legacy flat config
            if "users" not in cfg:
                old_user = cfg.get("admin_user", "admin")
                old_pass = cfg.get("admin_password", "healthprice")
                cfg = {"users": [_make_user(old_user, old_pass, "admin", "Administrador")]}
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=2, ensure_ascii=False)
            return cfg
        cfg = {"users": [_make_user("admin", "healthprice", "admin", "Administrador")]}
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return cfg

def save_config(cfg: dict):
    with _config_lock:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)

def find_user_by_username(cfg: dict, username: str):
    return next((u for u in cfg["users"] if u["username"] == username.strip().lower()), None)

def find_user_by_id(cfg: dict, uid: str):
    return next((u for u in cfg["users"] if u["id"] == uid), None)

# ─── Auth decorators ──────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Nao autenticado"}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify({"error": "Nao autenticado"}), 401
        if session.get("role") != "admin":
            return jsonify({"error": "Acesso negado — requer perfil Admin"}), 403
        return f(*args, **kwargs)
    return decorated

# ─── Portals ──────────────────────────────────────────────────────────────────

PORTAIS = {
    "bradesco": {
        "nome": "Bradesco Saúde",
        "script": "portal_Bradesco.py",
        "cor": "blue",
        "pasta_prefix": "BRADESCO",
        "timeout": 660,
        "logo": "/static/logos/bradesco_saude.png",
        "portal_url": "https://www.bradescosaude.com.br",
        "campos": [
            {"id": "cnpj",  "label": "CNPJ",  "tipo": "text",     "placeholder": "00.000.000/0001-00"},
            {"id": "cpf",   "label": "CPF",   "tipo": "text",     "placeholder": "000.000.000-00"},
            {"id": "senha", "label": "Senha", "tipo": "password", "placeholder": ""},
        ],
        "env_map": {"cnpj": "PORTAL_CNPJ", "cpf": "PORTAL_CPF", "senha": "PORTAL_SENHA"},
    },
    "saw": {
        "nome": "Unimed SAW",
        "script": "portal_saw.py",
        "cor": "green",
        "pasta_prefix": "UNIMED SAW",
        "timeout": 360,
        "logo": "/static/logos/logo_SAW.png",
        "portal_url": "https://www.unimed.coop.br",
        "campos": [
            {"id": "usuario", "label": "Usuario", "tipo": "text",     "placeholder": ""},
            {"id": "senha",   "label": "Senha",   "tipo": "password", "placeholder": ""},
        ],
        "env_map": {"usuario": "PORTAL_USUARIO", "senha": "PORTAL_SENHA"},
    },
    "unimed": {
        "nome": "Unimed PMW",
        "script": "portal_unimed.py",
        "cor": "orange",
        "pasta_prefix": "UNIMED PMW",
        "timeout": 360,
        "logo": "/static/logos/unimed.png",
        "portal_url": "https://www.unimed.coop.br",
        "campos": [
            {"id": "usuario", "label": "Usuario", "tipo": "text",     "placeholder": ""},
            {"id": "senha",   "label": "Senha",   "tipo": "password", "placeholder": ""},
        ],
        "env_map": {"usuario": "PORTAL_USUARIO", "senha": "PORTAL_SENHA"},
    },
}

# ─── Credentials ──────────────────────────────────────────────────────────────

_creds_lock = threading.Lock()

def load_creds():
    if os.path.exists(CREDS_FILE):
        with open(CREDS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {k: [] for k in PORTAIS}

def save_creds(data):
    with open(CREDS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ─── Notifications ────────────────────────────────────────────────────────────

_notif_lock = threading.Lock()

def _load_notifications():
    cfg = load_config()
    return cfg.get("notifications", [])

def _save_notifications(notifs: list):
    cfg = load_config()
    cfg["notifications"] = notifs
    save_config(cfg)

def _push_notification(title: str, body: str, notif_type: str = "info", target_users: list = None):
    """
    Adiciona uma notificação para todos os usuários ou para usuários específicos.
    notif_type: 'file' | 'info' | 'warning' | 'error'
    target_users: lista de usernames; None = todos
    """
    with _notif_lock:
        notifs = _load_notifications()
        nid = f"n_{int(datetime.now().timestamp()*1000)}"
        notifs.append({
            "id": nid,
            "title": title,
            "body": body,
            "type": notif_type,
            "created_at": datetime.now().isoformat(),
            "target_users": target_users,  # None = broadcast
            "read_by": [],
        })
        # Mantém apenas as últimas 200 notificações
        if len(notifs) > 200:
            notifs = notifs[-200:]
        _save_notifications(notifs)
    return nid

# ─── Jobs ─────────────────────────────────────────────────────────────────────

jobs = {}
_jobs_lock = threading.Lock()
_jc = 0

def _new_jid():
    global _jc
    _jc += 1
    return f"job_{_jc}_{int(datetime.now().timestamp())}"

def _is_cred_running(cred_id):
    for j in jobs.values():
        if j["status"] == "running":
            for t in j["tasks"]:
                if t["cred_id"] == cred_id:
                    return True
    return False

def _get_cred_files(pasta_nome):
    pasta = os.path.join(DOWNLOAD_BASE, pasta_nome)
    files = []
    if os.path.exists(pasta):
        for f in os.listdir(pasta):
            if f.startswith("."):
                continue
            fp = os.path.join(pasta, f)
            if os.path.isfile(fp):
                s = os.stat(fp)
                files.append({
                    "nome": f,
                    "tamanho": s.st_size,
                    "modificado": datetime.fromtimestamp(s.st_mtime).strftime("%d/%m/%Y %H:%M"),
                    "_mt": s.st_mtime,
                })
        files.sort(key=lambda x: x["_mt"], reverse=True)
        for f in files:
            del f["_mt"]
    return files

def _run_tasks_thread(job_id, tasks):
    try:
        for task in tasks:
            portal_key = task["portal"]
            cred_id    = task["cred_id"]
            info       = PORTAIS[portal_key]

            with _creds_lock:
                data = load_creds()
            cred = next((c for c in data.get(portal_key, []) if c["id"] == cred_id), None)

            if not cred:
                with _jobs_lock:
                    jobs[job_id]["logs"].append(f"[ERRO] Credencial {cred_id} nao encontrada. Pulando.")
                    jobs[job_id]["task_status"][cred_id] = "error"
                continue

            pasta_full = os.path.join(DOWNLOAD_BASE, cred["pasta"])
            os.makedirs(pasta_full, exist_ok=True)

            with _jobs_lock:
                jobs[job_id]["logs"].append(f"{'='*52}")
                jobs[job_id]["logs"].append(f"  {info['nome']}  —  {cred['unidade']}")
                jobs[job_id]["logs"].append(f"  Pasta: {cred['pasta']}")
                jobs[job_id]["logs"].append(f"{'='*52}")
                jobs[job_id]["current_cred"] = cred_id
                jobs[job_id]["task_status"][cred_id] = "running"

            env = os.environ.copy()
            env["PORTAL_DOWNLOAD_DIR"] = pasta_full
            for campo_id, env_var in info["env_map"].items():
                env[env_var] = cred.get(campo_id, "")

            script_path  = os.path.join(BASE_DIR, info["script"])
            timeout_sec  = info.get("timeout", 360)

            killed_by_timeout = threading.Event()
            login_failed      = threading.Event()
            rc = -1

            # arquivo de log persistente para este job+credencial
            ts_log   = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_name = f"{ts_log}_{portal_key}_{cred.get('unidade','').replace(' ','_')}.log"
            log_path = os.path.join(LOGS_DIR, log_name)

            try:
                process = subprocess.Popen(
                    [sys.executable, "-u", script_path],
                    cwd=BASE_DIR,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE,
                    env=env,
                )
                try:
                    process.stdin.write(b"\n" * 30)
                    process.stdin.flush()
                    process.stdin.close()
                except Exception:
                    pass

                def _watchdog():
                    try:
                        process.wait(timeout=timeout_sec)
                    except subprocess.TimeoutExpired:
                        killed_by_timeout.set()
                        try:
                            process.kill()
                        except Exception:
                            pass

                wt = threading.Thread(target=_watchdog, daemon=True)
                wt.start()

                with open(log_path, "w", encoding="utf-8") as log_f:
                    log_f.write(f"=== JOB {job_id} | {info['nome']} — {cred['unidade']} ===\n")
                    log_f.write(f"=== Início: {datetime.now().isoformat()} ===\n\n")
                    log_f.flush()
                    for raw in process.stdout:
                        line = raw.decode("utf-8", errors="replace").rstrip()
                        with _jobs_lock:
                            jobs[job_id]["logs"].append(line)
                        if "[LOGIN_FAILED]" in line:
                            login_failed.set()
                        log_f.write(line + "\n")
                        log_f.flush()
                    log_f.write(f"\n=== Fim: {datetime.now().isoformat()} ===\n")

                process.wait()
                rc = process.returncode

            except Exception as exc:
                with _jobs_lock:
                    jobs[job_id]["logs"].append(f"[ERRO] Falha ao iniciar processo: {exc}")
                rc = -1

            if killed_by_timeout.is_set():
                final_status = "timeout"
                with _jobs_lock:
                    jobs[job_id]["logs"].append(
                        f"[TIMEOUT] Tempo limite excedido ({timeout_sec}s) — {info['nome']} {cred['unidade']}"
                    )
            elif login_failed.is_set() or rc == 2:
                final_status = "login_failed"
            elif rc == 0:
                final_status = "success"
            else:
                final_status = "error"

            with _jobs_lock:
                if final_status == "done":
                    jobs[job_id]["logs"].append(f"[OK] {info['nome']} — {cred['unidade']} concluido com sucesso")
                elif final_status == "login_failed":
                    jobs[job_id]["logs"].append(
                        f"[LOGIN_FAILED] {info['nome']} — {cred['unidade']} : verifique usuario/senha"
                    )
                elif final_status != "timeout":
                    jobs[job_id]["logs"].append(
                        f"[ERRO] {info['nome']} — {cred['unidade']} finalizou com codigo {rc}"
                    )
                jobs[job_id]["task_status"][cred_id] = final_status

            with _creds_lock:
                saved = load_creds()
                for c in saved.get(portal_key, []):
                    if c["id"] == cred_id:
                        c["last_status"] = final_status
                        c["last_run"] = datetime.now().isoformat()
                        break
                save_creds(saved)

            # Notificação automática ao finalizar
            if final_status == "success":
                novos_arqs = _get_cred_files(cred["pasta"])
                nomes = ", ".join(f["nome"] for f in novos_arqs[:3]) if novos_arqs else "nenhum arquivo"
                _push_notification(
                    title=f"Novo download — {info['nome']} ({cred['unidade']})",
                    body=f"{len(novos_arqs)} arquivo(s) disponível(is): {nomes}",
                    notif_type="file",
                )
            elif final_status == "login_failed":
                _push_notification(
                    title=f"Falha de login — {info['nome']} ({cred['unidade']})",
                    body="Verifique usuário e senha nas configurações do convênio.",
                    notif_type="warning",
                )
            elif final_status == "error":
                _push_notification(
                    title=f"Erro na automação — {info['nome']} ({cred['unidade']})",
                    body=f"O script finalizou com código de erro {rc}. Verifique os logs.",
                    notif_type="error",
                )

        with _jobs_lock:
            jobs[job_id]["status"] = "done"
            jobs[job_id]["finished_at"] = datetime.now().isoformat()

    except Exception as e:
        with _jobs_lock:
            jobs[job_id]["logs"].append(f"[ERRO FATAL] {e}")
            jobs[job_id]["status"] = "error"
            jobs[job_id]["finished_at"] = datetime.now().isoformat()

# ─── Auth Routes ──────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET"])
def login_page():
    if session.get("logged_in"):
        return redirect(url_for("index"))
    return render_template("login.html")

@app.route("/login", methods=["POST"])
def login_post():
    cfg  = load_config()
    body = request.json or {}
    username = body.get("user", "").strip().lower()
    password = body.get("password", "")
    user = find_user_by_username(cfg, username)
    if user and user["password_hash"] == _hash_password(password, user["salt"]):
        must_change = user.get("must_change_password", False)
        session["logged_in"]          = True
        session["user_id"]            = user["id"]
        session["username"]           = user["username"]
        session["name"]               = user["name"]
        session["role"]               = user["role"]
        session["must_change_password"] = must_change
        return jsonify({"ok": True, "role": user["role"], "name": user["name"],
                        "must_change_password": must_change})
    return jsonify({"error": "Usuário ou senha incorretos"}), 401

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))

# ─── User Management Routes ───────────────────────────────────────────────────

@app.route("/api/users", methods=["GET"])
@admin_required
def list_users():
    cfg = load_config()
    return jsonify([
        {"id": u["id"], "username": u["username"], "name": u["name"],
         "role": u["role"], "created_at": u["created_at"],
         "must_change_password": u.get("must_change_password", False)}
        for u in cfg["users"]
    ])

@app.route("/api/users", methods=["POST"])
@admin_required
def create_user():
    body     = request.json or {}
    username = (body.get("username") or "").strip().lower()
    password = (body.get("password") or "").strip()
    name     = (body.get("name") or "").strip()
    role     = body.get("role", "operator")
    if not username or not password:
        return jsonify({"error": "Usuário e senha são obrigatórios"}), 400
    if role not in ("admin", "operator"):
        return jsonify({"error": "Perfil inválido"}), 400
    cfg = load_config()
    if find_user_by_username(cfg, username):
        return jsonify({"error": "Nome de usuário já existe"}), 409
    new_user = _make_user(username, password, role, name)
    new_user["must_change_password"] = True
    cfg["users"].append(new_user)
    save_config(cfg)
    return jsonify({"id": new_user["id"], "username": new_user["username"]}), 201

@app.route("/api/users/<uid>", methods=["PUT"])
@login_required
def update_user(uid):
    body = request.json or {}
    cfg  = load_config()
    user = find_user_by_id(cfg, uid)
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404

    is_self  = session.get("user_id") == uid
    is_admin = session.get("role") == "admin"

    if not is_self and not is_admin:
        return jsonify({"error": "Acesso negado"}), 403

    # Admin-only fields
    if is_admin:
        if "username" in body:
            new_uname = body["username"].strip().lower()
            if new_uname != user["username"] and find_user_by_username(cfg, new_uname):
                return jsonify({"error": "Nome de usuário já existe"}), 409
            user["username"] = new_uname
        if "name" in body:
            user["name"] = body["name"].strip()
        if "role" in body:
            if body["role"] not in ("admin", "operator"):
                return jsonify({"error": "Perfil inválido"}), 400
            # prevent removing last admin
            if user["role"] == "admin" and body["role"] != "admin":
                admins = [u for u in cfg["users"] if u["role"] == "admin"]
                if len(admins) <= 1:
                    return jsonify({"error": "Deve existir ao menos um Admin"}), 400
            user["role"] = body["role"]

    # Password change (self or admin)
    if "new_password" in body and body["new_password"]:
        new_pw = body["new_password"]
        # strength check
        if len(new_pw) < 8:
            return jsonify({"error": "A senha deve ter ao menos 8 caracteres"}), 400
        if not re.search(r'[A-Z]', new_pw):
            return jsonify({"error": "A senha deve conter ao menos uma letra maiúscula"}), 400
        # current password required only when: self-change AND not admin AND not forced change
        if is_self and not is_admin and not user.get("must_change_password", False):
            current = body.get("current_password", "")
            if user["password_hash"] != _hash_password(current, user["salt"]):
                return jsonify({"error": "Senha atual incorreta"}), 400
        new_salt = secrets.token_hex(16)
        user["salt"]                   = new_salt
        user["password_hash"]          = _hash_password(new_pw, new_salt)
        user["must_change_password"]   = False

    save_config(cfg)
    # refresh session if editing self
    if is_self:
        session["name"]                = user.get("name", session["name"])
        session["role"]                = user.get("role", session["role"])
        session["must_change_password"] = user.get("must_change_password", False)
    return jsonify({"ok": True})

@app.route("/api/users/<uid>", methods=["DELETE"])
@admin_required
def delete_user(uid):
    if session.get("user_id") == uid:
        return jsonify({"error": "Você não pode excluir sua própria conta"}), 400
    cfg = load_config()
    user = find_user_by_id(cfg, uid)
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    if user["role"] == "admin":
        admins = [u for u in cfg["users"] if u["role"] == "admin"]
        if len(admins) <= 1:
            return jsonify({"error": "Deve existir ao menos um Admin"}), 400
    cfg["users"] = [u for u in cfg["users"] if u["id"] != uid]
    save_config(cfg)
    return jsonify({"ok": True})

@app.route("/api/me")
@login_required
def api_me():
    return jsonify({
        "id":                   session.get("user_id"),
        "username":             session.get("username"),
        "name":                 session.get("name"),
        "role":                 session.get("role"),
        "must_change_password": session.get("must_change_password", False),
    })

# ─── App Routes ───────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    return render_template("index.html")

@app.route("/api/schema")
@login_required
def api_schema():
    return jsonify({
        k: {
            "nome": v["nome"],
            "cor": v["cor"],
            "pasta_prefix": v["pasta_prefix"],
            "campos": v["campos"],
            "logo": v.get("logo", ""),
            "portal_url": v.get("portal_url", ""),
        }
        for k, v in PORTAIS.items()
    })

@app.route("/api/portais")
@login_required
def api_portais():
    with _creds_lock:
        data = load_creds()

    result = {}
    for key, info in PORTAIS.items():
        creds_raw = data.get(key, [])
        enriched = []
        for c in creds_raw:
            last_job_info = None
            with _jobs_lock:
                for j in sorted(jobs.values(), key=lambda x: x["started_at"], reverse=True):
                    if c["id"] in j["task_status"]:
                        last_job_info = {
                            "job_id": j["id"],
                            "status": j["task_status"].get(c["id"]),
                            "started_at": j["started_at"],
                            "finished_at": j["finished_at"],
                        }
                        break

            files_raw = _get_cred_files(c["pasta"])
            for f in files_raw:
                f["url"] = f"/files/{key}/{c['id']}/{f['nome']}"

            enriched.append({
                "id": c["id"],
                "unidade": c["unidade"],
                "pasta": c["pasta"],
                "ativo": c.get("ativo", True),
                "running": _is_cred_running(c["id"]),
                "files": files_raw,
                "last_status": c.get("last_status"),
                "last_run": c.get("last_run"),
                "last_job": last_job_info,
            })

        result[key] = {
            "nome": info["nome"],
            "cor": info["cor"],
            "logo": info.get("logo", ""),
            "portal_url": info.get("portal_url", ""),
            "credenciais": enriched,
        }
    return jsonify(result)

@app.route("/api/credentials/<portal>", methods=["GET"])
@login_required
def get_credentials(portal):
    if portal not in PORTAIS:
        return jsonify({"error": "Portal invalido"}), 400
    with _creds_lock:
        data = load_creds()
    creds = data.get(portal, [])
    safe = []
    for c in creds:
        row = {k: v for k, v in c.items() if k != "senha"}
        row["senha"] = ""   # never send password back
        safe.append(row)
    return jsonify(safe)

@app.route("/api/credentials/<portal>", methods=["POST"])
@login_required
def add_credential(portal):
    if portal not in PORTAIS:
        return jsonify({"error": "Portal invalido"}), 400

    body = request.json or {}
    unidade = (body.get("unidade") or "").strip()
    if not unidade:
        return jsonify({"error": "Unidade obrigatoria"}), 400

    pasta = (body.get("pasta") or "").strip()
    if not pasta:
        pasta = f"{PORTAIS[portal]['pasta_prefix']} {unidade}".upper()

    cred = {
        "id": f"{portal}_{uuid.uuid4().hex[:8]}",
        "unidade": unidade,
        "pasta": pasta,
        "ativo": True,
    }
    for campo in PORTAIS[portal]["campos"]:
        cred[campo["id"]] = body.get(campo["id"], "")

    with _creds_lock:
        data = load_creds()
        data.setdefault(portal, []).append(cred)
        save_creds(data)

    os.makedirs(os.path.join(DOWNLOAD_BASE, pasta), exist_ok=True)
    return jsonify({"id": cred["id"], "pasta": pasta}), 201

@app.route("/api/credentials/<portal>/<cred_id>", methods=["PUT"])
@login_required
def update_credential(portal, cred_id):
    if portal not in PORTAIS:
        return jsonify({"error": "Portal invalido"}), 400

    body = request.json or {}
    with _creds_lock:
        data = load_creds()
        cred = next((c for c in data.get(portal, []) if c["id"] == cred_id), None)
        if not cred:
            return jsonify({"error": "Credencial nao encontrada"}), 404

        if "unidade" in body:
            cred["unidade"] = body["unidade"].strip()
        if "pasta" in body and body["pasta"].strip():
            cred["pasta"] = body["pasta"].strip()
        if "ativo" in body:
            cred["ativo"] = bool(body["ativo"])

        for campo in PORTAIS[portal]["campos"]:
            fid = campo["id"]
            if fid == "senha":
                if body.get("senha") and not body["senha"].startswith("\u2022"):
                    cred["senha"] = body["senha"]
            elif fid in body:
                cred[fid] = body[fid]

        save_creds(data)

    os.makedirs(os.path.join(DOWNLOAD_BASE, cred["pasta"]), exist_ok=True)
    return jsonify({"ok": True})

@app.route("/api/credentials/<portal>/<cred_id>", methods=["DELETE"])
@login_required
def delete_credential(portal, cred_id):
    if portal not in PORTAIS:
        return jsonify({"error": "Portal invalido"}), 400

    with _creds_lock:
        data = load_creds()
        before = len(data.get(portal, []))
        data[portal] = [c for c in data.get(portal, []) if c["id"] != cred_id]
        if len(data[portal]) == before:
            return jsonify({"error": "Credencial nao encontrada"}), 404
        save_creds(data)

    return jsonify({"ok": True})

@app.route("/api/run/<portal>", methods=["POST"])
@login_required
def api_run(portal):
    with _creds_lock:
        data = load_creds()

    if portal == "all":
        tasks = [
            {"portal": pk, "cred_id": c["id"]}
            for pk in PORTAIS
            for c in data.get(pk, [])
            if c.get("ativo", True)
        ]
    elif portal in PORTAIS:
        tasks = [
            {"portal": portal, "cred_id": c["id"]}
            for c in data.get(portal, [])
            if c.get("ativo", True)
        ]
    else:
        return jsonify({"error": "Portal invalido"}), 400

    if not tasks:
        return jsonify({"error": "Nenhuma credencial ativa encontrada"}), 400

    with _jobs_lock:
        for t in tasks:
            if _is_cred_running(t["cred_id"]):
                return jsonify({"error": "Uma credencial ja esta em execucao"}), 409

        job_id = _new_jid()
        jobs[job_id] = {
            "id": job_id,
            "tasks": tasks,
            "status": "running",
            "logs": [],
            "started_at": datetime.now().isoformat(),
            "finished_at": None,
            "current_cred": tasks[0]["cred_id"],
            "task_status": {t["cred_id"]: "pending" for t in tasks},
        }

    threading.Thread(target=_run_tasks_thread, args=(job_id, tasks), daemon=True).start()
    return jsonify({"job_id": job_id})

@app.route("/api/run/<portal>/<cred_id>", methods=["POST"])
@login_required
def api_run_cred(portal, cred_id):
    if portal not in PORTAIS:
        return jsonify({"error": "Portal invalido"}), 400

    with _creds_lock:
        data = load_creds()
    cred = next((c for c in data.get(portal, []) if c["id"] == cred_id), None)
    if not cred:
        return jsonify({"error": "Credencial nao encontrada"}), 404

    tasks = [{"portal": portal, "cred_id": cred_id}]

    with _jobs_lock:
        if _is_cred_running(cred_id):
            return jsonify({"error": "Ja em execucao"}), 409

        job_id = _new_jid()
        jobs[job_id] = {
            "id": job_id,
            "tasks": tasks,
            "status": "running",
            "logs": [],
            "started_at": datetime.now().isoformat(),
            "finished_at": None,
            "current_cred": cred_id,
            "task_status": {cred_id: "pending"},
        }

    threading.Thread(target=_run_tasks_thread, args=(job_id, tasks), daemon=True).start()
    return jsonify({"job_id": job_id})

@app.route("/api/job/<job_id>")
@login_required
def api_job(job_id):
    offset = int(request.args.get("offset", 0))
    with _jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job nao encontrado"}), 404
        return jsonify({
            "id": job["id"],
            "status": job["status"],
            "tasks": job["tasks"],
            "started_at": job["started_at"],
            "finished_at": job["finished_at"],
            "current_cred": job["current_cred"],
            "task_status": job["task_status"],
            "logs": job["logs"][offset:],
            "total_logs": len(job["logs"]),
        })

@app.route("/api/jobs")
@login_required
def api_jobs():
    with _jobs_lock:
        result = [
            {
                "id": j["id"],
                "tasks": j["tasks"],
                "status": j["status"],
                "started_at": j["started_at"],
                "finished_at": j["finished_at"],
            }
            for j in sorted(jobs.values(), key=lambda x: x["started_at"], reverse=True)[:20]
        ]
    return jsonify(result)

# ─── Notification API ─────────────────────────────────────────────────────────

@app.route("/api/notifications", methods=["GET"])
@login_required
def get_notifications():
    """Retorna notificações para o usuário atual (não lidas primeiro)."""
    username = session.get("username", "")
    with _notif_lock:
        notifs = _load_notifications()
    user_notifs = []
    for n in reversed(notifs):
        targets = n.get("target_users")
        if targets is not None and username not in targets:
            continue
        user_notifs.append({
            "id": n["id"],
            "title": n["title"],
            "body": n["body"],
            "type": n["type"],
            "created_at": n["created_at"],
            "read": username in n.get("read_by", []),
        })
    return jsonify(user_notifs[:50])

@app.route("/api/notifications/unread-count", methods=["GET"])
@login_required
def get_unread_count():
    username = session.get("username", "")
    with _notif_lock:
        notifs = _load_notifications()
    count = 0
    for n in notifs:
        targets = n.get("target_users")
        if targets is not None and username not in targets:
            continue
        if username not in n.get("read_by", []):
            count += 1
    return jsonify({"count": count})

@app.route("/api/notifications/<nid>/read", methods=["POST"])
@login_required
def mark_notification_read(nid):
    username = session.get("username", "")
    with _notif_lock:
        notifs = _load_notifications()
        for n in notifs:
            if n["id"] == nid:
                if username not in n.get("read_by", []):
                    n.setdefault("read_by", []).append(username)
                break
        _save_notifications(notifs)
    return jsonify({"ok": True})

@app.route("/api/notifications/read-all", methods=["POST"])
@login_required
def mark_all_read():
    username = session.get("username", "")
    with _notif_lock:
        notifs = _load_notifications()
        for n in notifs:
            targets = n.get("target_users")
            if targets is not None and username not in targets:
                continue
            if username not in n.get("read_by", []):
                n.setdefault("read_by", []).append(username)
        _save_notifications(notifs)
    return jsonify({"ok": True})

@app.route("/api/notifications", methods=["POST"])
@login_required
def create_notification():
    """Admin cria aviso/comunicado para usuários."""
    cfg = load_config()
    username = session.get("username", "")
    user = next((u for u in cfg.get("users", []) if u["username"] == username), None)
    if not user or user.get("role") not in ("admin", "ti"):
        return jsonify({"error": "Sem permissão"}), 403
    body = request.json or {}
    title = body.get("title", "").strip()
    msg   = body.get("body", "").strip()
    ntype = body.get("type", "info")
    targets = body.get("target_users")  # None = broadcast
    if not title or not msg:
        return jsonify({"error": "Título e mensagem são obrigatórios"}), 400
    nid = _push_notification(title, msg, ntype, targets)
    return jsonify({"ok": True, "id": nid})

@app.route("/api/notifications/<nid>", methods=["DELETE"])
@login_required
def delete_notification(nid):
    cfg = load_config()
    username = session.get("username", "")
    user = next((u for u in cfg.get("users", []) if u["username"] == username), None)
    if not user or user.get("role") not in ("admin", "ti"):
        return jsonify({"error": "Sem permissão"}), 403
    with _notif_lock:
        notifs = _load_notifications()
        notifs = [n for n in notifs if n["id"] != nid]
        _save_notifications(notifs)
    return jsonify({"ok": True})

@app.route("/api/logs/files")
@login_required
def list_log_files():
    """Lista arquivos de log persistidos em disco."""
    files = []
    if os.path.isdir(LOGS_DIR):
        for f in sorted(os.listdir(LOGS_DIR), reverse=True)[:50]:
            fp = os.path.join(LOGS_DIR, f)
            if os.path.isfile(fp):
                files.append({
                    "name": f,
                    "size": os.path.getsize(fp),
                    "modified": datetime.fromtimestamp(os.path.getmtime(fp)).isoformat(),
                })
    return jsonify(files)

@app.route("/api/logs/files/<filename>")
@login_required
def read_log_file(filename):
    """Lê conteúdo de um arquivo de log."""
    filename = os.path.basename(filename)  # prevent path traversal
    fp = os.path.join(LOGS_DIR, filename)
    if not os.path.isfile(fp):
        return jsonify({"error": "Arquivo não encontrado"}), 404
    with open(fp, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    return jsonify({"filename": filename, "content": content})

# ─── File Serving ─────────────────────────────────────────────────────────────

def _resolve_cred_pasta(portal: str, cred_id: str):
    """Return (pasta_path, cred) or (None, None)."""
    with _creds_lock:
        data = load_creds()
    cred = next((c for c in data.get(portal, []) if c["id"] == cred_id), None)
    if not cred:
        return None, None
    pasta = os.path.join(DOWNLOAD_BASE, cred["pasta"])
    return pasta, cred

@app.route("/files/<portal>/<cred_id>/<path:filename>")
@login_required
def serve_file(portal, cred_id, filename):
    if portal not in PORTAIS:
        return jsonify({"error": "Portal inválido"}), 400
    # prevent path traversal
    filename = os.path.basename(filename)
    pasta, cred = _resolve_cred_pasta(portal, cred_id)
    if not pasta:
        return jsonify({"error": "Credencial não encontrada"}), 404
    filepath = os.path.join(pasta, filename)
    if not os.path.isfile(filepath):
        return jsonify({"error": "Arquivo não encontrado"}), 404
    return send_file(filepath, as_attachment=True, download_name=filename)

@app.route("/files/<portal>/<cred_id>/zip")
@login_required
def serve_zip(portal, cred_id):
    import zipfile, io
    if portal not in PORTAIS:
        return jsonify({"error": "Portal inválido"}), 400
    pasta, cred = _resolve_cred_pasta(portal, cred_id)
    if not pasta:
        return jsonify({"error": "Credencial não encontrada"}), 404
    files = [f for f in os.listdir(pasta) if os.path.isfile(os.path.join(pasta, f)) and not f.startswith(".")]
    if not files:
        return jsonify({"error": "Nenhum arquivo para compactar"}), 404
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(os.path.join(pasta, f), f)
    buf.seek(0)
    zip_name = f"{cred['pasta'].replace(' ', '_')}.zip"
    return send_file(buf, as_attachment=True, download_name=zip_name, mimetype="application/zip")

@app.route("/api/files/<portal>/<cred_id>")
@login_required
def api_list_files(portal, cred_id):
    """List files with download URLs."""
    if portal not in PORTAIS:
        return jsonify({"error": "Portal inválido"}), 400
    pasta, cred = _resolve_cred_pasta(portal, cred_id)
    if not pasta:
        return jsonify({"error": "Credencial não encontrada"}), 404
    files = _get_cred_files(cred["pasta"])
    for f in files:
        f["url"] = f"/files/{portal}/{cred_id}/{f['nome']}"
    zip_url = f"/files/{portal}/{cred_id}/zip" if files else None
    return jsonify({"files": files, "zip_url": zip_url, "pasta": cred["pasta"]})

# ─── Schedule ─────────────────────────────────────────────────────────────────

_DEFAULT_SCHEDULE = {
    "enabled": False,
    "times": ["08:00", "18:00"],
    "last_auto_runs": {},   # "HH:MM": "YYYY-MM-DD" — tracks last day each slot ran
}

def get_schedule() -> dict:
    cfg = load_config()
    sched = cfg.get("schedule", _DEFAULT_SCHEDULE.copy())
    # ensure all keys present
    for k, v in _DEFAULT_SCHEDULE.items():
        sched.setdefault(k, v)
    return sched

def save_schedule(sched: dict):
    cfg = load_config()
    cfg["schedule"] = sched
    save_config(cfg)

def _next_run_dt(sched: dict) -> datetime | None:
    """Return the next scheduled datetime, or None if disabled/no times."""
    if not sched.get("enabled") or not sched.get("times"):
        return None
    now = datetime.now()
    candidates = []
    for t in sched["times"]:
        try:
            h, m = map(int, t.split(":"))
        except Exception:
            continue
        cand = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if cand <= now:
            cand += timedelta(days=1)
        candidates.append(cand)
    return min(candidates) if candidates else None

def _scheduler_loop():
    """Daemon thread: every 30 s check whether a scheduled slot should fire."""
    while True:
        try:
            sched = get_schedule()
            if sched.get("enabled"):
                now   = datetime.now()
                today = date.today().isoformat()
                last  = sched.get("last_auto_runs", {})
                for slot in sched.get("times", []):
                    try:
                        h, m = map(int, slot.split(":"))
                    except Exception:
                        continue
                    # fire if we are within the target minute and haven't fired today
                    if now.hour == h and now.minute == m and last.get(slot) != today:
                        # mark before firing to prevent double-trigger
                        last[slot] = today
                        sched["last_auto_runs"] = last
                        save_schedule(sched)
                        _trigger_auto_run(slot)
        except Exception:
            pass
        threading.Event().wait(30)

def _trigger_auto_run(slot: str):
    """Build task list for all active credentials and start a job."""
    with _creds_lock:
        data = load_creds()
    tasks = [
        {"portal": pk, "cred_id": c["id"]}
        for pk in PORTAIS
        for c in data.get(pk, [])
        if c.get("ativo", True)
    ]
    if not tasks:
        return
    with _jobs_lock:
        # skip if any task is already running
        running_ids = {
            t["cred_id"]
            for j in jobs.values()
            if j["status"] == "running"
            for t in j["tasks"]
        }
        tasks = [t for t in tasks if t["cred_id"] not in running_ids]
        if not tasks:
            return
        job_id = _new_jid()
        jobs[job_id] = {
            "id":           job_id,
            "tasks":        tasks,
            "status":       "running",
            "logs":         [f"[AUTO] Execução automática agendada — {slot}"],
            "started_at":   datetime.now().isoformat(),
            "finished_at":  None,
            "current_cred": tasks[0]["cred_id"],
            "task_status":  {t["cred_id"]: "pending" for t in tasks},
            "auto":         True,
        }
    threading.Thread(target=_run_tasks_thread, args=(job_id, tasks), daemon=True).start()

@app.route("/api/schedule", methods=["GET"])
@login_required
def api_get_schedule():
    sched = get_schedule()
    next_dt = _next_run_dt(sched)
    return jsonify({
        "enabled": sched["enabled"],
        "times":   sched["times"],
        "next_run": next_dt.isoformat() if next_dt else None,
        "last_auto_runs": sched.get("last_auto_runs", {}),
    })

@app.route("/api/schedule", methods=["PUT"])
@admin_required
def api_put_schedule():
    body = request.json or {}
    sched = get_schedule()
    if "enabled" in body:
        sched["enabled"] = bool(body["enabled"])
    if "times" in body:
        times = []
        for t in body["times"]:
            t = str(t).strip()
            if re.match(r'^\d{2}:\d{2}$', t):
                times.append(t)
        if len(times) < 1:
            return jsonify({"error": "Informe ao menos um horário válido (HH:MM)"}), 400
        sched["times"] = times
    save_schedule(sched)
    next_dt = _next_run_dt(sched)
    return jsonify({"ok": True, "next_run": next_dt.isoformat() if next_dt else None})

# ─── Alerts Config ────────────────────────────────────────────────────────────

_DEFAULT_ALERTS = {
    "email": {"enabled": False, "address": ""},
    "telegram": {"enabled": False, "token": "", "chat_id": ""},
    "whatsapp": {"enabled": False, "number": ""},
    "events": {
        "login_failed": True,
        "new_table": True,
        "success": False,
        "error": True,
    },
}

def get_alerts_cfg() -> dict:
    cfg = load_config()
    alerts = cfg.get("alerts", {})
    for k, v in _DEFAULT_ALERTS.items():
        if k not in alerts:
            alerts[k] = v
    return alerts

def save_alerts_cfg(alerts: dict):
    cfg = load_config()
    cfg["alerts"] = alerts
    save_config(cfg)

@app.route("/api/alerts", methods=["GET"])
@login_required
def api_get_alerts():
    return jsonify(get_alerts_cfg())

@app.route("/api/alerts", methods=["PUT"])
@admin_required
def api_put_alerts():
    body = request.json or {}
    alerts = get_alerts_cfg()
    for channel in ("email", "telegram", "whatsapp"):
        if channel in body:
            alerts[channel].update(body[channel])
    if "events" in body:
        alerts["events"].update(body["events"])
    save_alerts_cfg(alerts)
    return jsonify({"ok": True})

# ─── System Status ─────────────────────────────────────────────────────────────

@app.route("/api/status")
@login_required
def api_system_status():
    with _creds_lock:
        data = load_creds()
    total_creds = sum(len(v) for v in data.values())
    active_creds = sum(1 for v in data.values() for c in v if c.get("ativo", True))
    running = sum(1 for v in data.values() for c in v if _is_cred_running(c["id"]))
    with _jobs_lock:
        today = datetime.now().strftime("%Y-%m-%d")
        today_downloads = 0
        today_errors = 0
        for j in jobs.values():
            if j["started_at"][:10] == today:
                for status in j["task_status"].values():
                    if status == "done":
                        today_downloads += 1
                    elif status in ("error", "login_failed", "timeout"):
                        today_errors += 1
    sched = get_schedule()
    next_dt = _next_run_dt(sched)
    return jsonify({
        "server": "online",
        "total_creds": total_creds,
        "active_creds": active_creds,
        "running": running,
        "today_downloads": today_downloads,
        "today_errors": today_errors,
        "scheduler_enabled": sched.get("enabled", False),
        "next_run": next_dt.isoformat() if next_dt else None,
    })

if __name__ == "__main__":
    load_config()  # ensure config / migrate on startup
    # start scheduler daemon thread
    threading.Thread(target=_scheduler_loop, daemon=True, name="hpm-scheduler").start()
    print("=" * 50)
    print("  HealthPrice Monitor — Dashboard Web")
    print("  Agendador iniciado (verifica a cada 30s)")
    print("  Acesse: http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
