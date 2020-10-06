from functools import wraps
import io
import os
import re
import secrets
from urllib.parse import urlencode

from authlib.integrations.flask_client import OAuth
from flask import Flask, render_template, session, url_for, request, abort, jsonify, redirect
from jinja2 import Markup
import pymongo
import qrcode
import qrcode.image.svg


app = Flask("myapp")
app.secret_key = os.environ["SECRET_KEY"]

oauth = OAuth(app)

auth0 = oauth.register(
    "auth0",
    client_id=os.environ["CLIENT_ID"],
    client_secret=os.environ["CLIENT_SECRET"],
    api_base_url=f"https://{os.environ['AUTH0_DOMAIN']}",
    access_token_url=f'https://{os.environ["AUTH0_DOMAIN"]}/oauth/token',
    authorize_url=f'https://{os.environ["AUTH0_DOMAIN"]}/authorize',
    client_kwargs={
        "scope": "openid profile email",
    },
)

mc = pymongo.MongoClient(os.environ["MONGO_URL"])
db = mc[os.environ["MONGO_DB"]]


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "profile" not in session:
            # Redirect to Login page here
            return redirect("/")
        return f(*args, **kwargs)

    return decorated


@app.route("/")
def get_index():
    if request.args.get("code"):
        code = request.args["code"].strip()
        seq = db.sequences.find_one({"slug": code})
        if seq:
            return redirect(url_for("get_sequence", slug=code))
        else:
            return redirect(url_for("get_index"))

    if "profile" in session:
        graphs = list(db.graphs.find({"userId": session["profile"]["user_id"]}))
        sequences = list(db.sequences.find({"userId": session["profile"]["user_id"]}))
    else:
        graphs = None
        sequences = None

    return render_template(
        "index.html", profile=session.get("profile"), graphs=graphs, sequences=sequences,
    )


@app.route("/login")
def login():
    return auth0.authorize_redirect(redirect_uri=url_for("callback_handling", _external=True))


@app.route("/callback")
def callback_handling():
    # Handles response from token endpoint
    auth0.authorize_access_token()
    resp = auth0.get("userinfo")
    userinfo = resp.json()

    # Store the user information in flask session.
    session["jwt_payload"] = userinfo
    session["profile"] = {
        "user_id": userinfo["sub"],
        "name": userinfo["name"],
        "picture": userinfo["picture"],
    }
    return redirect("/")


@app.route("/logout")
def logout():
    session.clear()
    params = {
        "returnTo": url_for("get_index", _external=True),
        "client_id": os.environ["CLIENT_ID"],
    }
    return redirect(auth0.api_base_url + "/v2/logout?" + urlencode(params))


@app.route("/new-sequence")
@requires_auth
def get_new_sequence():
    return render_template("new-sequence.html")


@app.route("/new-sequence", methods=["POST"])
@requires_auth
def post_new_sequence():
    errors = []
    slug = request.form["slug"].strip()
    title = request.form["title"].strip()

    if not title:
        errors.append("Please fill in the title field")

    if not slug:
        errors.append("Please fill in the slug field")
    elif not re.match(r"[a-z0-9-]{1,100}$", slug):
        errors.append("Please use lower case letters and dashes for a unique slug")
    elif db.graphs.find_one({"slug": slug}):
        errors.append("This slug is already taken")

    if errors:
        return render_template(
            "new-sequence.html",
            title=request.form.get("title"),
            slug=request.form.get("slug"),
            errors=errors,
        )

    obj = {"slug": slug, "userId": session["profile"]["user_id"], "title": title, "current": None}
    db.sequences.insert_one(obj)
    return redirect(url_for("get_draft_sequence", slug=slug))


@app.route("/draft-sequences/<slug>")
@requires_auth
def get_draft_sequence(slug):
    seq = db.sequences.find_one({"slug": slug})
    if not seq:
        abort(404)
    if seq["userId"] != session["profile"]["user_id"]:
        abort(401)

    questions = list(db.questions.find({"sequence.slug": slug}))

    return render_template("draft-sequence.html", seq=seq, questions=questions)


@app.route("/draft-sequence/<slug>/update", methods=["GET", "POST"])
@requires_auth
def get_draft_sequence_update(slug):
    seq = db.sequences.find_one({"slug": slug})
    if not seq:
        abort(404)

    if seq["userId"] != session["profile"]["user_id"]:
        abort(401)

    if request.method == "POST":
        errors = []
        title = request.form["title"].strip()
        if not title:
            errors.append("Please fill in the title field")
        if errors:
            return render_template(
                "draft-sequence-update.html", seq=seq, title=title, errors=errors
            )
        db.sequences.update_one({"slug": slug}, {"$set": {"title": title}})
        return redirect(url_for("get_draft_sequence", slug=slug))

    return render_template("draft-sequence-update.html", seq=seq, title=seq["title"], errors=[])


@app.route("/draft-sequence/<slug>/new-question", methods=["GET", "POST"])
@requires_auth
def get_draft_sequence_new_question(slug):
    seq = db.sequences.find_one({"slug": slug})
    if not seq:
        abort(404)

    if seq["userId"] != session["profile"]["user_id"]:
        abort(401)

    if request.method == "POST":
        errors = []
        question_slug = request.form["slug"].strip()
        question = request.form["question"].strip()
        choices = [
            request.form.get("choice1"),
            request.form.get("choice2"),
            request.form.get("choice3"),
            request.form.get("choice4"),
            request.form.get("choice5"),
        ]
        choices = [text for c in choices for text in [(c or "").strip()] if text]

        if not question:
            errors.append("Please fill in the question field")

        if not question_slug:
            errors.append("Please fill in the slug field")
        elif not re.match(r"[a-z0-9-]{1,100}$", question_slug):
            errors.append("Please use lower case letters and dashes for a unique slug")
        elif db.questions.find_one({"sequence.slug": slug, "slug": question_slug}):
            errors.append("This slug is already taken")

        if not choices:
            errors.append("Please provide some choices")

        if errors:
            return render_template(
                "draft-sequence-new-question.html",
                seq=seq,
                question=request.form.get("question"),
                slug=request.form.get("slug"),
                choice1=request.form.get("choice1"),
                choice2=request.form.get("choice2"),
                choice3=request.form.get("choice3"),
                choice4=request.form.get("choice4"),
                choice5=request.form.get("choice5"),
                errors=errors,
            )

        obj = {
            "sequence": {"_id": seq["_id"], "slug": slug},
            "slug": request.form["slug"],
            "userId": session["profile"]["user_id"],
            "question": request.form["question"],
            "data": [{"group": c, "value": 0} for c in choices],
            "responders": [],
        }
        db.questions.insert_one(obj)
        return redirect(url_for("get_draft_sequence", slug=slug))

    return render_template("draft-sequence-new-question.html", seq=seq)


@app.route("/draft-sequence/<slug>/questions/<question_slug>/delete", methods=["GET", "POST"])
@requires_auth
def get_draft_sequence_question_delete(slug, question_slug):
    seq = db.sequences.find_one({"slug": slug})
    if not seq:
        abort(404)

    if seq["userId"] != session["profile"]["user_id"]:
        abort(401)

    question = db.questions.find_one({"sequence.slug": slug, "slug": question_slug})
    if not question:
        abort(404)

    if request.method == "POST":
        db.questions.delete_one({"sequence.slug": slug, "slug": question_slug})
        return redirect(url_for("get_draft_sequence", slug=slug))

    return render_template("draft-sequence-question-delete.html", seq=seq, question=question)


@app.route("/s/<slug>/dashboard")
@requires_auth
def get_sequence_dashboard(slug):
    seq = db.sequences.find_one({"slug": slug})

    if not seq:
        abort(404)

    if seq["userId"] != session["profile"]["user_id"]:
        abort(401)

    join_url = url_for("get_sequence", slug=seq["slug"], _external=True)
    if not seq["current"]:

        img = qrcode.make(join_url, image_factory=qrcode.image.svg.SvgPathImage)
        s = io.BytesIO()
        img.save(s)
        join_svg = s.getvalue().decode("utf-8")

        return render_template(
            "sequence-dashboard-start.html", seq=seq, join_url=join_url, join_svg=Markup(join_svg)
        )

    if not seq:
        abort(404)
    questions = db.questions.find({"sequence.slug": slug}, sort=[("_id", pymongo.ASCENDING)])

    previous_question = None
    current_question = None
    next_question = None
    for q in questions:
        if q["slug"] == seq["current"]:
            current_question = q
        elif not current_question:
            previous_question = q
        elif current_question and not next_question:
            next_question = q
            break

    data_source_url = url_for(
        "get_question_data", slug=slug, question_slug=current_question["slug"]
    )
    return render_template(
        "sequence-dashboard-question.html",
        seq=seq,
        previous_question=previous_question,
        current_question=current_question,
        next_question=next_question,
        join_url=join_url,
        data_source_url=data_source_url,
    )


@app.route("/s/<slug>/questions/<question_slug>/data")
@requires_auth
def get_question_data(slug, question_slug):
    seq = db.sequences.find_one({"slug": slug})

    if not seq:
        abort(404)

    if seq["userId"] != session["profile"]["user_id"]:
        abort(401)

    question = db.questions.find_one({"sequence.slug": slug, "slug": question_slug})
    if not question:
        abort(404)

    return jsonify(question["data"])


@app.route("/s/<slug>/dashboard/start", methods=["POST"])
@requires_auth
def post_sequence_dashboard_start(slug):
    seq = db.sequences.find_one({"slug": slug})

    if not seq:
        abort(404)

    if seq["userId"] != session["profile"]["user_id"]:
        abort(401)

    question = db.questions.find_one({"sequence.slug": slug}, sort=[("_id", pymongo.ASCENDING)])
    db.sequences.update_one({"slug": slug}, {"$set": {"current": question["slug"]}})
    return redirect(url_for("get_sequence_dashboard", slug=slug))


@app.route("/s/<slug>/dashboard/move", methods=["POST"])
@requires_auth
def post_sequence_dashboard_progress(slug):
    seq = db.sequences.find_one({"slug": slug})

    if not seq:
        abort(404)

    if seq["userId"] != session["profile"]["user_id"]:
        abort(401)

    db.sequences.update_one({"slug": slug}, {"$set": {"current": request.form["question"]}})
    return redirect(url_for("get_sequence_dashboard", slug=slug))


@app.route("/s/<slug>")
def get_sequence(slug):
    seq = db.sequences.find_one({"slug": slug})
    if not seq:
        abort(404)

    if not session.get("uid"):
        session["uid"] = secrets.token_urlsafe()

    if not seq["current"]:
        return render_template("sequence-waiting.html", seq=seq)

    question = db.questions.find_one({"sequence.slug": slug, "slug": seq["current"]})
    if not question:
        return render_template("sequence-waiting.html", seq=seq)

    is_answered = session["uid"] in question.get("responders", [])

    if is_answered:
        return render_template("sequence-waiting.html", seq=seq)

    return redirect(url_for("get_sequence_question", slug=slug, question_slug=question["slug"]))


@app.route("/s/<slug>/questions/<question_slug>", methods=["GET", "POST"])
def get_sequence_question(slug, question_slug):
    seq = db.sequences.find_one({"slug": slug})
    if not seq:
        abort(404)

    if not session.get("uid"):
        return redirect(url_for("get_sequence", slug=slug))

    question = db.questions.find_one({"sequence.slug": slug, "slug": question_slug})
    if not question:
        return redirect(url_for("get_sequence", slug=slug))

    if session["uid"] in question["responders"]:
        return redirect(url_for("get_sequence", slug=slug))

    if request.method == "POST":
        value = request.form["choice"]
        db.questions.update_one(
            {"sequence.slug": slug, "slug": question_slug, "data.group": value},
            {"$addToSet": {"responders": session["uid"]}, "$inc": {f"data.$.value": 1}},
        )
        return redirect(url_for("get_sequence", slug=slug))

    return render_template("sequence-question.html", seq=seq, question=question)


@app.route("/new-survey")
@requires_auth
def get_new_survey():
    return render_template("new-survey.html")


@app.route("/new-survey", methods=["POST"])
@requires_auth
def post_new_survey():
    errors = []
    slug = request.form["slug"].strip()
    question = request.form["question"].strip()
    choices = [
        request.form.get("choice1"),
        request.form.get("choice2"),
        request.form.get("choice3"),
        request.form.get("choice4"),
        request.form.get("choice5"),
    ]
    choices = [text for c in choices for text in [(c or "").strip()] if text]

    if not question:
        errors.append("Please fill in the question field")

    if not slug:
        errors.append("Please fill in the slug field")
    elif not re.match(r"[a-z0-9-]{1,100}$", slug):
        errors.append("Please use lower case letters and dashes for a unique slug")
    elif db.graphs.find_one({"slug": slug}):
        errors.append("This slug is already taken")

    if not choices:
        errors.append("Please provide some choices")

    if errors:
        return render_template(
            "new-survey.html",
            question=request.form.get("question"),
            slug=request.form.get("slug"),
            choice1=request.form.get("choice1"),
            choice2=request.form.get("choice2"),
            choice3=request.form.get("choice3"),
            choice4=request.form.get("choice4"),
            choice5=request.form.get("choice5"),
            errors=errors,
        )

    obj = {
        "slug": request.form["slug"],
        "userId": session["profile"]["user_id"],
        "question": request.form["question"],
        "data": [{"group": c, "value": 0} for c in choices],
    }
    db.graphs.insert_one(obj)
    return redirect(url_for("get_graph", slug=slug))


@app.route("/surveys/<slug>/graph")
def get_graph(slug):
    graph = db.graphs.find_one({"slug": slug})
    if not graph:
        abort(404)
    data_source_url = url_for("get_data", slug=graph["slug"])
    response_url = url_for("get_respond", slug=graph["slug"], _external=True)

    img = qrcode.make(response_url, image_factory=qrcode.image.svg.SvgPathImage)
    s = io.BytesIO()
    img.save(s)
    respond_svg = s.getvalue().decode("utf-8")

    return render_template(
        "graph.html",
        question=graph["question"],
        data_source_url=data_source_url,
        response_url=response_url,
        respond_svg=Markup(respond_svg),
    )


@app.route("/r/<slug>")
def get_respond(slug):
    graph = db.graphs.find_one({"slug": slug})
    if not graph:
        abort(404)

    return render_template("respond.html", question=graph["question"], choices=graph["data"])


@app.route("/r/<slug>", methods=["POST"])
def post_respond(slug):
    value = request.form["choice"]
    db.graphs.update_one({"slug": slug, "data.group": value}, {"$inc": {f"data.$.value": 1}})
    return redirect(url_for("get_graph", slug=slug))


@app.route("/surveys/<slug>/data")
def get_data(slug):
    graph = db.graphs.find_one({"slug": slug})
    if not graph:
        abort(404)
    return jsonify(graph["data"])
