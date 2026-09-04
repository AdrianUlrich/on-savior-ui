"""Build the standalone build-planner applet from its template + the shared payload."""

from payload import inject

out = inject("planner_template.html", "planner.html", script_name="planner.js")
print(f"wrote {out}")
