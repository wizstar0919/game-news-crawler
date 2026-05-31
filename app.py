from flask import Flask, render_template, jsonify, request
from crawler import fetch_all, get_stats, sort_items
from translator import translate_to_korean
import store

app = Flask(__name__)


@app.route("/")
def index():
    sort_by = request.args.get("sort", "date")
    items = sort_items(fetch_all(), sort_by)
    stats = get_stats(items)
    return render_template("index.html", items=items, stats=stats, sort_by=sort_by)


@app.route("/api/news")
def api_news():
    category = request.args.get("category")
    source = request.args.get("source")
    sort_by = request.args.get("sort", "date")
    items = fetch_all()
    if category and category != "all":
        items = [i for i in items if i["category"] == category]
    if source:
        items = [i for i in items if i["source"] == source]
    items = sort_items(items, sort_by)
    return jsonify({"count": len(items), "items": items})


@app.route("/api/refresh")
def api_refresh():
    items = fetch_all(force=True)
    return jsonify({"count": len(items), "stats": get_stats(items)})


@app.route("/api/bookmarks")
def api_bookmarks():
    """해당 코드(사용자)가 북마크한 link 목록을 반환한다."""
    code = (request.args.get("code") or "").strip()
    return jsonify({"links": store.get_user_bookmarks(code)})


@app.route("/api/bookmark", methods=["POST"])
def api_bookmark():
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    link = data.get("link", "")
    bookmarked = bool(data.get("bookmarked", False))
    if not code:
        return jsonify({"ok": False, "error": "code required"}), 400
    if not link:
        return jsonify({"ok": False, "error": "link required"}), 400
    ok = store.set_user_bookmark(code, link, bookmarked)
    if not ok:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "link": link, "bookmarked": bookmarked})


@app.route("/api/translate", methods=["POST"])
def api_translate():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "")
    summary = data.get("summary", "")
    return jsonify({
        "title": translate_to_korean(title),
        "summary": translate_to_korean(summary),
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
