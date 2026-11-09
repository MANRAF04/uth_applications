import json

from fetch_theses import diff, extract_table, parse_theses

COLUMNS = [
    {"id": 3, "name": "ΤΙΤΛΟΣ"},
    {"id": 4, "name": "ΠΕΡΙΓΡΑΦΗ"},
    {"id": 6, "name": "ΕΠΙΒΛΕΠΩΝ ΚΑΘΗΓΗΤΗΣ"},
    {"id": 8, "name": "ΔΙΑΘΕΣΙΜΟ"},
    {"id": 9, "name": "ΗΜΕΡΟΜΗΝΙΑ    (ΜΜ/ΗΗ/ΕΕ)"},
]


def row(record_id, title, available="", description=""):
    values = {"3": title, "4": description, "6": "Sup", "8": available, "9": ""}
    return {
        "record_id": str(record_id),
        "created_at": f"2026-01-0{record_id} 00:00:00",
        "updated_at": "2026-01-10 00:00:00",
        "content": {column_id: {"value": value} for column_id, value in values.items()},
    }


rows = [
    row(1, "ΤΙΤΛΟΣ"),
    row(2, ""),
    row(3, "A", "1777735644000", '<p>x&amp;y\t</p><ul><li>one <a href="https://u.gr">link</a></li></ul>'),
    row(4, "B"),
]
page = "<script>window.tablesomeTables = " + json.dumps([{"items": {"columns": COLUMNS, "rows": rows}}]) + ";</script>"
newest, oldest = parse_theses(extract_table(page))

assert (newest["id"], oldest["id"]) == (4, 3)
assert oldest["available"] and not newest["available"]
assert oldest["description"] == "x&y\n- one link (https://u.gr)"

changes = diff(
    [newest, oldest, dict(oldest, id=9)],
    [dict(newest, available=True), dict(oldest, title="A2", available=False), dict(newest, id=5)],
)
assert changes == {
    "New": ["[5] B (Sup)"],
    "Removed": ["[9] A (Sup)"],
    "Now available": ["[4] B (Sup)"],
    "No longer available": ["[3] A2 (Sup)"],
    "Changed": ["[3] A2 (Sup): title"],
}
print("ok")
