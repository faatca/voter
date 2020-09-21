from flask import Flask, render_template, session, url_for, request, abort, jsonify, redirect
import io
import os
import pymongo
import re
import qrcode
import qrcode.image.svg
from jinja2 import Markup


app = Flask("myapp")
app.secret_key = b"fal30zd-()(3p2m_-214"

mc = pymongo.MongoClient(os.environ["MONGO_URL"])
db = mc[os.environ["MONGO_DB"]]

# py -m venv venv
# venv\Scripts\pip install flask pymongo qrcode[pil] 
# set MONGO_DB=voter
# set MONGO_URL=mongodb://kubla.redbrick.xyz
# set FLASK_APP=voteapp.py
# set FLASK_ENV=development
# venv\Scripts\flask.exe run


@app.route("/")
def get_index():
    return render_template("index.html")


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
