"""Build the analysis report page from its template + the shared payload."""

from payload import inject

out = inject("report_template.html", "report.html")
print(f"wrote {out}")
