import io
import os
import re
import secrets
from flask import Flask, render_template, session, url_for, request, abort, jsonify, redirect
import pymongo
import qrcode
import qrcode.image.svg
from jinja2 import Markup


app = Flask("myapp")
app.secret_key = b"fal30zd-()(3p2m_-214"

mc = pymongo.MongoClient(os.environ["MONGO_URL"])
db = mc[os.environ["MONGO_DB"]]

# py -m venv venv
# venv\Scripts\pip install flask pymongo qrcode[pil]
# set MONGO_URL=mongodb://kubla.redbrick.xyz
# set MONGO_DB=voter
# set FLASK_APP=voteapp.py
# set FLASK_ENV=development
# venv\Scripts\flask.exe run


@app.route("/")
def get_index():
    if request.args.get("code"):
        seq = db.sequences.find_one({"slug": request.args["code"]})
        if seq:
            return redirect(url_for("get_sequence", slug=request.args["code"]))
        else:
            return redirect(url_for("get_index"))
    return render_template("index.html")


@app.route("/new-sequence")
def get_new_sequence():
    return render_template("new-sequence.html")


@app.route("/new-sequence", methods=["POST"])
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

    obj = {"slug": slug, "title": title, "current": None}
    db.sequences.insert_one(obj)
    return redirect(url_for("get_draft_sequence", slug=slug))


@app.route("/draft-sequences/<slug>")
def get_draft_sequence(slug):
    seq = db.sequences.find_one({"slug": slug})
    if not seq:
        abort(404)

    questions = list(db.questions.find({"sequence.slug": slug}))

    return render_template("draft-sequence.html", seq=seq, questions=questions)


@app.route("/draft-sequence/<slug>/update", methods=["GET", "POST"])
def get_draft_sequence_update(slug):
    seq = db.sequences.find_one({"slug": slug})
    if not seq:
        abort(404)

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
def get_draft_sequence_new_question(slug):
    seq = db.sequences.find_one({"slug": slug})
    if not seq:
        abort(404)

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
            "question": request.form["question"],
            "data": [{"group": c, "value": 0} for c in choices],
            "responders": []
        }
        db.questions.insert_one(obj)
        return redirect(url_for("get_draft_sequence", slug=slug))

    return render_template("draft-sequence-new-question.html", seq=seq)


@app.route("/draft-sequence/<slug>/questions/<question_slug>/delete", methods=["GET", "POST"])
def get_draft_sequence_question_delete(slug, question_slug):
    seq = db.sequences.find_one({"slug": slug})
    if not seq:
        abort(404)

    question = db.questions.find_one({"sequence.slug": slug, "slug": question_slug})
    if not question:
        abort(404)

    if request.method == "POST":
        db.questions.delete_one({"sequence.slug": slug, "slug": question_slug})
        return redirect(url_for("get_draft_sequence", slug=slug))

    return render_template("draft-sequence-question-delete.html", seq=seq, question=question)


@app.route("/s/<slug>/dashboard")
def get_sequence_dashboard(slug):
    seq = db.sequences.find_one({"slug": slug})

    if not seq:
        abort(404)

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

    data_source_url = url_for("get_question_data", slug=slug, question_slug=current_question["slug"])
    return render_template(
        "sequence-dashboard-question.html",
        seq=seq,
        previous_question=previous_question,
        current_question=current_question,
        next_question=next_question,
        join_url=join_url,
        data_source_url=data_source_url
    )


@app.route("/s/<slug>/questions/<question_slug>/data")
def get_question_data(slug, question_slug):
    question = db.questions.find_one({"sequence.slug": slug, "slug": question_slug})
    if not question:
        abort(404)
    return jsonify(question["data"])


@app.route("/s/<slug>/dashboard/start", methods=["POST"])
def post_sequence_dashboard_start(slug):
    question = db.questions.find_one({"sequence.slug": slug}, sort=[("_id", pymongo.ASCENDING)])
    db.sequences.update_one({"slug": slug}, {"$set": {"current": question["slug"]}})
    return redirect(url_for("get_sequence_dashboard", slug=slug))


@app.route("/s/<slug>/dashboard/move", methods=["POST"])
def post_sequence_dashboard_progress(slug):
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
def get_new_survey():
    return render_template("new-survey.html")


@app.route("/new-survey", methods=["POST"])
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
